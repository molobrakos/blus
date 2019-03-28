Simple Bluez D-Bus python client interface

Use like:

```python
class Observer(blus.DeviceObserver):

    def seen(self, manager, path, device):
        alias = device.get("Alias")
        print("Seeing %s at %s" % (alias, path))

        # device = blus.proxy_for(device)
        # device.trusted = True
        # device.Pair()
        # etc ...


blus.DeviceManager(Observer()).scan(transport="le")
```

  Other example:
  https://github.com/molobrakos/toothbrush/blob/master/toothbrush
