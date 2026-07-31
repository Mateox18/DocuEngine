from abc import abstractmethod


class base:
    def __init__(self):
        pass
    @abstractmethod
    def parse(self, path:str):
        pass