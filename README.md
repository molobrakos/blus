Simple Bluez D-Bus python client interface

Use like:

```python
class Observer(blus.DeviceObserver):

  def discovered(self, path, device):
    alias = device.get("Alias")
    print("Discovered %s at %s" % alias, path))

  def seen(self, path, device):
    alias = device.get("Alias")
    print("Seeing %s at %s" % alias, path))

  blus.scan(blus.DeviceManager(Observer()), transport="le")
  ```
  
  Other example:
  https://github.com/molobrakos/toothbrush/blob/master/toothbrush
