
Reliable data transfer using BLE.

## L2CAP  (Logical Link Control and Adaptation Protocol)

* flow-control
* multiplexing
* ERTM: Enhanced Retransmission Mode
  * checksums
  * re-transmission

in esp-idf, there is L2CAP_FCR_ERTM_MODE.
https://github.com/espressif/esp-idf/blob/master/components/bt/host/bluedroid/stack/l2cap/l2c_fcr.c

there appears to be STREAMING mode TODO
https://github.com/espressif/esp-idf/blob/master/components/bt/host/bluedroid/stack/l2cap/l2c_fcr.c#L1778


https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-54/out/en/host/logical-link-control-and-adaptation-protocol-specification.html


https://community.infineon.com/t5/ModusToolbox/Enable-ERTM-on-L2CAP-server/td-p/272448



# web
https://petewarden.github.io/ble_file_transfer/website/index.html
https://github.com/petewarden/ble_file_transfer/blob/main/website/index.html

https://github.com/troublegum/micropyserver
https://github.com/danvk/dygraphs
