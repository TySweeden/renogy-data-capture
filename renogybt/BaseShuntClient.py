import os
from threading import Timer
import logging
import configparser
import time
from .Utils import bytes_to_int, int_to_bytes, crc16_modbus
from .BLE import DeviceManager, Device

# Base class that works with all Renogy family devices
# Should be extended by each client with its own parsers and section definitions
# Section example: {'register': 5000, 'words': 8, 'parser': self.parser_func}

ALIAS_PREFIX = 'RMTShunt300'
ALIAS_PREFIX_PRO = 'Shunt300'
NOTIFY_CHAR_UUID = "0000c411-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID  = "" # RMTShunt sends all data over notify to any connected device
READ_TIMEOUT = 30 # (seconds)

class BaseClient:
    def __init__(self, config):
        self.config: configparser.ConfigParser = config
        self.manager = None
        self.device = None
        self.data = {}
        self.device_id = self.config['device'].getint('device_id')
        self.sections = []
        self.section_index = 0
        logging.info(f"Init {self.__class__.__name__}: {self.config['device']['alias']} => {self.config['device']['mac_addr']}")

    def connect(self):
        self.manager = DeviceManager(adapter_name=self.config['device']['adapter'], mac_address=self.config['device']['mac_addr'], alias=self.config['device']['alias'])
        self.manager.discover()

        if not self.manager.device_found:
            logging.error(f"Device not found: {self.config['device']['alias']} => {self.config['device']['mac_addr']}, please check the details provided.")
            for dev in self.manager.devices():
                if dev.alias() != None and (dev.alias().startswith(ALIAS_PREFIX) or dev.alias().startswith(ALIAS_PREFIX_PRO)):
                    logging.debug(f"Possible device found! ======> {dev.alias()} > [{dev.mac_address}]")
            self.__stop_service()

        self.device = Device(mac_address=self.config['device']['mac_addr'], manager=self.manager, on_resolved=self.__on_resolved, on_data=self.on_data_received, on_connect_fail=self.__on_connect_fail, notify_uuid=NOTIFY_CHAR_UUID, write_uuid=WRITE_CHAR_UUID)
        
        try:
            self.device.connect()
            self.manager.run()
        except Exception as e:
            self.__on_error(True, e)
        except KeyboardInterrupt:
            self.__on_error(False, "KeyboardInterrupt")

    def disconnect(self):
        self.device.disconnect()
        self.__stop_service()

    def __on_resolved(self):
        logging.info("resolved services")
        # self.poll_data() if self.config['data'].getboolean('enable_polling') == True else self.read_section()

    def read_section(self):
        index = self.section_index
        if self.device_id == None or len(self.sections) == 0:
            return logging.error("base client cannot be used directly")
        # request = self.create_generic_read_request(self.device_id, 3, self.sections[index]['register'], self.sections[index]['words']) 
        # self.device.characteristic_write_value(request)
        # self.read_timer = Timer(READ_TIMEOUT, self.on_read_timeout)
        # self.read_timer.start()
        
    def on_data_received(self, response):
        logging.debug(msg=f"DEBUG on_data_received")
        # self.read_timer.cancel()
        operation = bytes_to_int(response, 1, 1)

        if operation == 87: # notify operation
            logging.info("on_data_received: response for notify operation")
            if (self.section_index < len(self.sections) and
                self.sections[self.section_index]['parser'] != None and
                self.sections[self.section_index]['words'] == len(response)):
                # parse and update data
                self.data = self.sections[self.section_index]['parser'](response)
                self.__safe_callback(self.on_data_callback, self.data)
        else:
            logging.warn("on_data_received: unknown operation={}".format(operation))

    def on_read_timeout(self):
        logging.error("on_read_timeout => please check your device_id!")
        self.disconnect()

    def __on_error(self, connectFailed = False, error = None):
        logging.error(f"Exception occured: {error}")
        self.__safe_callback(self.on_error_callback, error)
        self.__stop_service() if connectFailed else self.disconnect()

    def __on_connect_fail(self, error):
        logging.error(f"Connection failed: {error}")
        self.__safe_callback(self.on_error_callback, error)
        self.__stop_service()

    def __safe_callback(self, calback, param):
        if calback is not None:
            try:
                calback(self, param)
            except Exception as e:
                logging.error(f"__safe_callback => exception in callback! {e}")

    def __stop_service(self):
        # if self.poll_timer is not None and self.poll_timer.is_alive():
        #     self.poll_timer.cancel()
        # if self.poll_timer is not None and self.read_timer is not None:
        #     self.read_timer.cancel()
        self.manager.stop()
        # os._exit(os.EX_OK) ## ONLY CALL IF YOU WANT TO STOP THE APP PROCESS