Simple Bluez D-Bus python client interface

Use like:

```python
import blus
class Observer(blus.DeviceObserver):

    def seen(self, manager, path, device):
        alias = device.get("Alias")
        print("Seeing %s at %s" % (alias, path))

        # device = blus.proxy_for(device)
        # device.Pair()
        # device.Connect()
        # etc ...


blus.DeviceManager(Observer()).scan()
```

```
> python3 scanner.py
Seeing 4B-CF-80-09-16-72 at /org/bluez/hci0/dev_4B_CF_80_09_16_72
Seeing 77-0C-65-0A-7C-0F at /org/bluez/hci0/dev_77_0C_65_0A_7C_0F
Seeing 42-90-C6-B6-F0-8A at /org/bluez/hci0/dev_42_90_C6_B6_F0_8A
Seeing Apple Pencil at /org/bluez/hci0/dev_68_24_3F_07_9F_F1
Seeing 7C-38-5D-97-D3-10 at /org/bluez/hci0/dev_7C_38_5D_97_D3_10
Seeing Suunto 9 123210000194 at /org/bluez/hci0/dev_0D_8C_DA_37_BC_50
Seeing 64-2D-A9-2D-14-96 at /org/bluez/hci0/dev_64_2D_A9_2D_14_96
Seeing 78-66-CF-91-BC-38 at /org/bluez/hci0/dev_78_66_CF_91_BC_38
Seeing 66-F5-90-3B-76-FD at /org/bluez/hci0/dev_66_F5_90_3B_76_FD
Seeing [AV] Samsung Soundbar MS750 at /org/bluez/hci0/dev_54_BD_79_26_FE_D1
Seeing [TV] Samsung 7 Series (43) at /org/bluez/hci0/dev_FC_03_9F_5B_D1_1A
Seeing [TV] Samsung Q9 Series (65) at /org/bluez/hci0/dev_7C_64_56_9F_14_DF
```

  Other example:
  https://github.com/molobrakos/toothbrush/blob/master/toothbrush
