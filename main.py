import sys
import time
import config
import requests
import urllib.parse
from sqlalchemy import (
    MetaData,
    Table,
    Column,
    String,
    create_engine,
    insert,
    select,
    update,
    delete
)
from sqlalchemy_utils import database_exists, create_database


engine = create_engine(config.DATABASE_URL, echo=False)
if not database_exists(engine.url):
    create_database(engine.url)
connection = engine.connect()

metadata_obj = MetaData(engine)

store_table = Table(
    'store',
    metadata_obj,
    Column('id', String(255), primary_key=True),
    Column('title', String(255)),
    Column('image', String(255)),
    Column('status', String(255))
)

metadata_obj.create_all()


class UberEats:
    def __init__(self):
        self.session = self.create_session()

    def create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                'x-csrf-token': 'x',
                'x-uber-xps': '%7B%7D'
            }
        )
        return session

    def format_address(self, address_data: str) -> str:
        return urllib.parse.quote(address_data)

    def check_address(self, show: bool = False) -> bool:
        payload = {
            'placeId': config.ADDRESS,
            'provider': 'google_places'
        }
        url = (
            'https://www.ubereats.com/api/getDeliveryLocationV1'
            f'?localeCode={config.REGION}'
        )
        result = self.session.post(url, data=payload)
        result_json = result.json()

        status = result_json['status']
        if status == 'success':
            address_data = result_json['data']

            formatted_data = self.format_address(str(address_data))
            self.session.cookies.set(
                'uev2.loc', formatted_data, domain='ubereats.com'
            )

            if show is True:
                address = address_data['address']['address1']
                print(f'Your address: {address}')
            return True

        else:
            print('Address not found')
            return False

    def add_store(self, store_name: str) -> None:
        result = self.check_address()
        if result is False:
            return

        payload = {
            'userQuery': store_name,
            'vertical': 'ALL'
        }
        url = (
            'https://www.ubereats.com/api/getSearchSuggestionsV1'
            f'?localeCode={config.REGION}'
        )
        result = self.session.post(url, data=payload)
        result_json = result.json()

        status = result_json['status']
        if status == 'success':
            store_data = result_json['data']
            if len(store_data) == 0:
                print('Store not found')
                return

            store_info = store_data[0]['store']
            store_id = store_info['uuid']
            store_title = store_info['title']
            store_image = store_info['heroImageUrl']

            stmt = insert(store_table).values(
                id=store_id, title=store_title, image=store_image, status=None
            )
            result = connection.execute(stmt)
            print(f'Store \'{store_title}\' added to database')

        else:
            print('Store not found')
            return

    def get_store_list(self) -> list:
        stmt = select(store_table)
        return list(connection.execute(stmt))

    def get_store_info(self, store_id: str) -> dict:
        payload = {
            'storeUuid': store_id
        }
        url = (
            'https://www.ubereats.com/api/getStoreV1'
            f'?localeCode={config.REGION}'
        )
        result = self.session.post(url, data=payload)
        return result.json()

    def send_discord_notification(
        self, store_info: dict, saved_status: str
    ) -> None:
        if saved_status is None:
            saved_status = 'None'

        payload = {
            'username': 'Uber Eats Monitoring',
            'embeds': [
                {
                    'title': store_info[1],
                    'fields': [
                        {
                            'name': 'Previous status',
                            'value': saved_status,
                            'inline': False
                        },
                        {
                            'name': 'Current status',
                            'value': store_info[3],
                            'inline': False
                        },
                    ],
                    'thumbnail': {
                        'url': store_info[2]
                    },
                }
            ]
        }
        url = config.WEBHOOK
        self.session.post(url, json=payload)

    def check_store_updates(self, saved_store_info: dict) -> None:
        store_id = saved_store_info[0]
        saved_status = saved_store_info[3]
        store_result = self.get_store_info(store_id)

        status = store_result['status']
        if status != 'success':
            return

        store_data = store_result['data']
        store_title = store_data['title']
        store_image = store_data['heroImageUrls'][1]['url']

        store_metadata = store_data['storeInfoMetadata']
        store_status = (
            store_metadata['storeAvailablityStatus']['state']
        )

        new_store_info = (
            store_id, store_title, store_image, store_status
        )

        if saved_store_info != new_store_info:
            stmt = update(store_table).where(
                store_table.c.id == store_id
            ).values(
                title=store_title,
                image=store_image,
                status=store_status
            )
            connection.execute(stmt)

        if saved_status != store_status:
            self.send_discord_notification(
                new_store_info, saved_status
            )

    def run_task(self) -> None:
        while True:
            store_list = self.get_store_list()

            for store_info in store_list:
                try:
                    self.check_store_updates(store_info)
                except Exception:
                    continue

            time.sleep(15)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        print('No action specified')
        sys.exit()

    stmt = select(store_table)
    result = list(connection.execute(stmt))

    if len(result) == 0:
        print('No stores added')
    else:
        print('Store list:')
        for count in range(len(result)):
            print(f'{count+1}. {result[count][1]}')

    action = sys.argv[1]
    uber_eats = UberEats()

    if action == 'run':
        uber_eats.run_task()

    elif action == 'add':
        store_name = input('Store name: ')
        uber_eats.add_store(store_name)

    elif action == 'remove':
        if len(result) == 0:
            exit()

        store_count = int(input('Store number: '))
        store_id = result[store_count-1][0]

        stmt = delete(store_table).where(store_table.c.id == store_id)
        connection.execute(stmt)

    elif action == 'address':
        uber_eats.check_address(show=True)
