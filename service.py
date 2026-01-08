import abc


class BaseService:
    #__metaclass__ = abc.ABCMeta

    def __init__(self):
        pass

    @abc.abstractmethod
    async def start(self, background: bool, args:dict):
        raise NotImplementedError()

    @abc.abstractmethod
    async def stop(self):
        # close all resources
        raise NotImplementedError()