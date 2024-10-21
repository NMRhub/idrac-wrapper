#!/usr/bin/env python3
import requests
import json

class IDRACRedfish:
    def __init__(self, host, username, password):
        self.host = host
        self.username = username
        self.password = password
        self.base_url = f"https://{host}/redfish/v1"
        self.session = requests.Session()
        self.session.verify = False  # Disable SSL verification (only do this for internal secure environments)
        self.headers = {'Content-Type': 'application/json'}

    def login(self):
        url = f"{self.base_url}/SessionService/Sessions"
        payload = {
            'UserName': self.username,
            'Password': self.password
        }
        response = self.session.post(url, data=json.dumps(payload), headers=self.headers)
        if response.status_code in [200, 201]:
            self.headers['X-Auth-Token'] = response.headers.get('X-Auth-Token')
            return True
        else:
            print(f"Failed to login: {response.status_code}, {response.text}")
            return False

    def logout(self):
        url = f"{self.base_url}/SessionService/Sessions"
        self.session.delete(url, headers=self.headers)

    def get_location_info(self):
        """Fetches location information (DataCenter, Room, Aisle, Rack, and Slot)"""
        url = f"{self.base_url}/Chassis/System.Embedded.1"  # Modify based on iDRAC version, this is a common endpoint.
        response = self.session.get(url, headers=self.headers)

        if response.status_code == 200:
            chassis_data = response.json()

            print(chassis_data) #data is in here, but not in location below

            # The location information is typically available under 'Oem' -> 'Dell' -> 'Location'
            location_info = chassis_data.get('Oem', {}).get('Dell', {}).get('Location', {})

            data_center = location_info.get('DataCenter', 'Unknown')
            room = location_info.get('Room', 'Unknown')
            aisle = location_info.get('Aisle', 'Unknown')
            rack = location_info.get('Rack', 'Unknown')
            slot = location_info.get('Slot', 'Unknown')

            return {
                'DataCenter': data_center,
                'Room': room,
                'Aisle': aisle,
                'Rack': rack,
                'Slot': slot
            }
        else:
            print(f"Failed to get location info: {response.status_code}, {response.text}")
            return None


# Example usage
if __name__ == "__main__":
    # Replace with your iDRAC IP, username, and password
    host = "idrac-turing.nmrbox.org"
    username = "root"
    password = input("password ") 

    idrac = IDRACRedfish(host, username, password)

    if idrac.login():
        location_info = idrac.get_location_info()
        if location_info:
            print("Location Information:")
            for key, value in location_info.items():
                print(f"{key}: {value}")

        idrac.logout()

