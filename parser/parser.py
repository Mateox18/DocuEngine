from abc import abstractmethod


class Parser(object):
    def __init__(self):
        pass
    @abstractmethod
    def parse(self, path:str):
        pass