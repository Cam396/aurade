# Shill to NetworkManager adapter

AuraDE exposes the `org.chromium.flimflam` interface that Ash expects and
backs it with the host's NetworkManager state. Wi-Fi services are derived from
NetworkManager access points, not from the wireless interface itself. An
interface with no scan result therefore does not become a fake online network.

## Check the real network stack

Run these commands on the installed system, either locally or over SSH:

```bash
nmcli radio wifi on
nmcli device status
nmcli device wifi rescan
nmcli device wifi list
```

Join a visible network without placing the passphrase in shell history:

```bash
nmcli device wifi connect "NETWORK NAME" --ask
```

Check the result and the route:

```bash
nmcli connection show --active
nmcli device show
ip route
```

## Check the bridge

```bash
systemctl status NetworkManager shill-nm-adapter --no-pager
journalctl -u shill-nm-adapter -b --no-pager
dbus-send --system --print-reply \
  --dest=org.chromium.flimflam / \
  org.chromium.flimflam.Manager.GetProperties
```

The adapter deliberately does not invent cellular services. Ethernet remains
represented by its physical device, while Wi-Fi rows appear only for real
NetworkManager access points. Connecting from Ash writes or updates a normal
NetworkManager profile and activates it through NetworkManager's D-Bus API.

If SSH is enabled on a test machine, copy and install a rebuilt
`shill-nm-adapter` package, then restart the service. Do not copy over a live
daemon while it is handling a connection attempt.
