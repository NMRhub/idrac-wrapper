#!/usr/bin/env python3
import requests
import json
import sys
import getpass  # For securely getting the password from user input

class IDRACRedfish:
    def __init__(self, host, password):
        self.host = host
        self.username = "root"  # The username is set to 'root'
        self.password = password
        self.base_url = f"https://{host}/redfish/v1"
        self.session = requests.Session()
        self.session.verify = False  # Disable SSL verification (use this only for internal networks)
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

            # Extracting location information from 'Location' field
            location_info = chassis_data.get('Location', {})
            location_info_raw = location_info.get('Info', '')
            info_format = location_info.get('InfoFormat', '')

            # Parse location based on the InfoFormat
            location_parts = location_info_raw.split(';')
            format_parts = info_format.split(';')

            location_map = dict(zip(format_parts, location_parts))

            data_center = location_map.get('DataCenter', 'Unknown')
            room = location_map.get('RoomName', 'Unknown')
            aisle = location_map.get('Aisle', 'Unknown')
            rack = location_map.get('RackName', 'Unknown')
            slot = location_map.get('RackSlot', 'Unknown')

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


if __name__ == "__main__":
    # Check if the host argument is passed
    if len(sys.argv) < 2:
        print("Usage: python idrac_location.py <iDRAC-host>")
        sys.exit(1)

    # The first command-line argument is the host
    host = sys.argv[1]

    # Use getpass to securely get the password from the user
    password = getpass.getpass(prompt="Enter iDRAC password for user 'root': ")

    # Initialize the IDRACRedfish class with the host and password
    idrac = IDRACRedfish(host, password)

    if idrac.login():
        location_info = idrac.get_location_info()
        if location_info:
            print("Location Information:")
            for key, value in location_info.items():
                print(f"{key}: {value}")

        idrac.logout()

