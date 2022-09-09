

class VirtualMedia:

    def __init__(self,data:dict):
        self.id = data['Id']
        self.device = data['Name']
        self.name = data['ImageName']
        self.path = data['Image']

    @property
    def empty(self):
        return self.name is None

    def __str__(self):
        if self.name:
            return f"{self.device}: {self.name}"
        return f"{self.device}: empty"
