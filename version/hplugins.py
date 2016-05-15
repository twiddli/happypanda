"""
"""
import logging
import os
import uuid

from PyQt5.QtCore import pyqtWrapperType

log = logging.getLogger(__name__)
log_i = log.info
log_d = log.debug
log_w = log.warning
log_e = log.error
log_c = log.critical

class Plugins:
	""
	_connections = []
	_plugins = {}
	hooks = {}


	def register(self, plugin):
		assert isinstance(plugin, HPluginMeta)
		self.hooks[plugin.ID] = {}
		self._plugins[plugin.NAME] = plugin()

	def _connectHooks(self):
		for plugin_name, pluginid, h_name, handler in self._connections:
			log_i("{}:{} connection to {}:{}".format(plugin_name, handler, pluginid, h_name))
			try:
				p = self.hooks[pluginid]
			except KeyError:
				log_e("Could not find plugin with plugin id: {}".format(pluginid))
				return
			try:
				h = p[h_name]
			except KeyError:
				log_e("Could not find pluginhook with name: {}".format(h_name))
				return
		
			h.addHandler(handler)

	def __getattr__(self, key):
		try:
			return self._plugins[key]
		except KeyError:
			return None

registered = Plugins()


class HPluginMeta(pyqtWrapperType):

	_plugins = registered

	def __init__(cls, name, bases, dct):
		if not isinstance(cls._plugins, Plugins):
			log_e("Plugins should not have an attribute named _plugins")
			return

		if not name.endswith("HPlugin"):
			log_e("Main plugin class should end with name HPlugin")
			return

		if not hasattr(cls, "ID"):
			log_e("ID attribute is missing")
			return
		cls.ID = cls.ID.replace('-', '')
		if not hasattr(cls, "NAME"):
			log_e("NAME attribute is missing")
			return
		if not hasattr(cls, "VERSION"):
			log_e("VERSION attribute is missing")
			return
		if not hasattr(cls, "AUTHOR"):
			log_e("AUTHOR attribute is missing")
			return
		if not hasattr(cls, "DESCRIPTION"):
			log_e("DESCRIPTION attribute is missing")
			return

		try:
			val = uuid.UUID(cls.ID, version=4)
			assert val.hex == cls.ID
		except ValueError:
			log_e("Invalid plugin id. UUID4 is required.")
			return
		except AssertionError:
			log_e("Invalid plugin id. A valid UUID4 is required.")
			return

		if not isinstance(cls.NAME, str):
			log_e("Plugin name should be a string")
			return
		if not isinstance(cls.VERSION, tuple):
			log_e("Plugin version should be a tuple with 3 integers")
			return
		if not isinstance(cls.AUTHOR, str):
			log_e("Plugin author should be a string")
			return
		if not isinstance(cls.DESCRIPTION, str):
			log_e("Plugin description should be a string")
			return

		super().__init__(name, bases, dct)

		setattr(cls, "newHook", cls.newHook)
		setattr(cls, "registerHook", cls.registerHook)
		setattr(cls, "__getattr__", cls.__getattr__)

		cls._plugins.register(cls)

	def registerHook(self, pluginid, hookName, handler):
		""
		assert isinstance(pluginid, str) and isinstance(hookName, str) and callable(handler), ""
		self._plugins._connections.append((self.NAME, pluginid.replace('-', ''), hookName, handler))

	def newHook(self, hookName):
		assert isinstance(hookName, str), ""

		class Hook:
			_handlers = set()
			def addHandler(self, handler):
				self._handlers.add(handler)

			def __call__(self, *args, **kwargs):
				for handlers in self._handlers:
					handlers(*args, **kwargs)

		h = Hook()

		self._plugins.hooks[self.ID][hookName] = h

	def __getattr__(self, key):
		try:
			return self._plugins.hooks[self.ID][key]
		except KeyError:
			return None