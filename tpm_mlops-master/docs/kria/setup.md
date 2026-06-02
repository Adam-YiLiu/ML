# Kria Board Set Up

### Open the Raspberry Pi Imager

1. Select "Use custom" for the OS, and choose the Ubuntu image.
2. Select the microSD card as the target.
3. Flash the image (this erases everything on the card).

### Set Up an Ethernet-over-USB Gadget Network (macOS)

Simulates a local network using static IPs.

1. Open System Settings -> Network
2. Find the **Ethernet** interface connected to the Kria board.
3. Config:
   - Configure IPv4 manually
   - Set the IP address to `192.168.100.1`
   - Set the subnet mask to `255.255.255.0`

#### Update the Network Configuration File

Update the `network-config` file in `/Volumes/system-boot`:

```yml
#cloud-config
version: 2
renderer: NetworkManager
ethernets:
  eth0:
    dhcp4: no
    addresses: [192.168.100.2/24]
    gateway4: 192.168.100.1
    nameservers:
      addresses: [8.8.8.8, 1.1.1.1]
```

### Boot the Board

1. Insert the microSD into the KV260.
2. Connect the Ethernet directly between the Mac and the KV260.
3. Connect power to the KV260 (give it a 1-2 mins to boot).

### Connect to the Board via SSH

```sh
ssh <username>@<hostname>.local
```

### Connect to the Board via VSCode Remote SSH

```sh
# if you don't already have a key
ssh-keygen -t rsa -b 4096

# then, copy the key to the Kria board
# ssh-copy-id prathmesh@kria.local
ssh-copy-id <username>@<hostname>.local
```

# macOS Internet Sharing

**Note:** Ensure you're not connected to a 802.1X network.

1. Open System Settings → Sharing

- Go to System Settings > General > Sharing
- Scroll to "Internet Sharing"
- Click the ⓘ next to it

2. Set Internet Sharing Options

- Share your connection from: Wi-Fi
- To computers using: Ethernet (this is the interface connected to your Kria)

Enable Internet Sharing by toggling it on.

Your Mac may briefly disable and re-enable Ethernet. Wait a few seconds.

## Add DNS to NetworkManager Connection

```sh
# find connection
> nmcli connection show
NAME          UUID                                  TYPE      DEVICE
netplan-eth0  626dd384-8b3d-3690-9511-192b2c79b3fd  ethernet  eth0

# add DNS to 'netplan-eth0'
> sudo nmcli connection modify "netplan-eth0" ipv4.dns "8.8.8.8 1.1.1.1"
> sudo nmcli connection modify "netplan-eth0" ipv4.ignore-auto-dns yes

# restart the connection
> nmcli connection down "netplan-eth0" && nmcli connection up "netplan-eth0"
```

# Vitis AI Setup

## On the Host Machine

### Clone the Vitis AI Repository

```sh
git clone https://github.com/Xilinx/Vitis-AI
cd Vitis-AI
```

### Start the Docker Container

```sh
# This command mounts your current directory (Vitis-AI) to /workspace inside the container
docker run --rm -it -v $PWD:/workspace xilinx/vitis-ai-pytorch-cpu:latest
```

### Download and Prepare the ResNet50 Model Inside the Docker Container

```sh
cd /workspace
mkdir models && cd models
wget https://www.xilinx.com/bin/public/openDownload?filename=resnet50-zcu102_zcu104_kv260-r3.0.0.tar.gz -O resnet50.tar.gz
tar -xzf resnet50.tar.gz
```

### Transfer the Model to the KV260

```sh
scp -r models/resnet50 <username>@<hostname>.local:/home/<username>/
```

## On the KV260

### Install Vitis AI Runtime and Dependencies

```sh
# try this before the following code block
git clone https://github.com/Xilinx/Kria-PYNQ.git
cd Kria-PYNQ/

sudo bash install.sh -b KV260
```

After running install.sh, you will be able to access jupyter notebook on `kria.local` in your Host machine's browser (assuming you've connected the two with an Ethernet cable).

```sh
# old
# sudo apt update
# sudo apt install -y vitis-ai-runtime libjson-c-dev libopencv-dev python3-pip
# pip3 install pynq pandas matplotlib

# sudo apt update
# sudo apt install -y \
#   build-essential \
#   python3-dev \
#   python3-pip \
#   python3-venv \
#   libssl-dev \
#   libffi-dev \
#   libxml2-dev \
#   libxslt1-dev \
#   libboost-dev \
#   libsensors4-dev \
#   libjson-c-dev \
#   libopencv-dev \
#   libdrm-dev \
#   jupyter-notebook

# pip3 install --upgrade pip
# pip3 install pandas matplotlib

# sudo apt install -y vitis-ai-runtime
```

### Install the ResNet50 Model

```sh
cd /home/root/resnet50
sudo mkdir -p /usr/share/vitis_ai_library/models
sudo cp -r resnet50 /usr/share/vitis_ai_library/models/
```

# References

- [Kria Setup Documentation](https://xilinx.github.io/kria-apps-docs/kv260/2022.1/linux_boot/ubuntu_24_04/build/html/docs/intro.html)
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
- [Ubuntu Server 22.04](https://ubuntu.com/download/amd#kria-k26)
- [Vitis AI Setup](https://xilinx.github.io/Vitis-AI/3.0/html/docs/quickstart/mpsoc.html?highlight=kv260)
- [Docker Installation](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository)
