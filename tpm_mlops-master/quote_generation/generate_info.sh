#!/bin/sh
sudo ps -eo user,cmd --no-headers | awk '$1=="root" || $1=="daemon" || $1=="messagebus" || $1=="systemd-network" || $1=="nobody" {print $2}' | sort -u | while read exe; do   [ -f "$exe" ] && sha256sum "$exe"; done
