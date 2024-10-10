import getpass

import keyring


def get_password():
    """Get password from console"""
    return getpass.getpass("Enter password for iDrac:  ")


class PasswordContext:
    """Set keyring password if no exception raised in context"""

    def __init__(self,account):
        self.account = account

    def __enter__(self):
        self.password = keyring.get_password('idrac', self.account)
        need_pass = self.password is None
        if need_pass:
            print(f"Need password for account {self.account}")
            self.password = get_password()
        return  self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            keyring.set_password('idrac', self.account,self.password)

    def password_fn(self):
        return self.password

    def clear(self):
        keyring.delete_password('idrac', self.account)
        print(f"Need password for account {self.account}")
        self.password = get_password()
