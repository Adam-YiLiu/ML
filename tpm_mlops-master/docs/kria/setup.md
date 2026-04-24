# Kria Board Set Up

## 1. Flashing the OS

Download the OS image from the [Kria website](https://www.xilinx.com/member/forms/download/design-license-xef.html?filename=xilinx-kv260-dpu-v2022.2-v3.0.0.img.gz) and flash it to your SD card using a tool like [Balena Etcher](https://www.balena.io/etcher/).

## 2. Initial Configuration

1. Insert the flashed SD card into the Kria board and power it on.
2. Find the board's IP address by either
    - Connecting a monitor and keyboard to the board and running `ip addr`
    - Checking your router's connected devices list for a new entry (look for "xilinx" or similar)
3. SSH into the board with the default user `petalinux`, no password required
4. Run `sudo dnf update` to update the package lists. This will prompt you to set a new password for the `petalinux` user.

## 3. Install Vitis SDK
This project uses Vitis AI runtime 3.0.

1. Download the Vitis AI runtime [here](https://www.xilinx.com/bin/public/openDownload?filename=vitis-ai-runtime-3.0.0.tar.gz)
2. Transfer the file to the Kria board using `scp`:
    ```bash
    host:$ scp vitis-ai-runtime-3.0.0.tar.gz petalinux@<KRIA_IP_ADDRESS>:/home/petalinux/
    host:$ ssh petalinux@<KRIA_IP_ADDRESS>
    petalinux@kria:~$ tar -xzf vitis-ai-runtime-3.0.0.tar.gz
    ```
3. Install the packages
    ```bash
    cd vitis-ai-runtime-3.0.0/2022.2/aarch64/centos
    sudo ./setup.sh
    ```
4. Verify installation
    ```bash
    python3 -c "import vart; print(vart.__version__)"
    ```

## 4. Install and load the DPU firmware

This installs the firmware for the FPGA-based DPU accelerator on the Kria board.

> [!IMPORTANT]
> The board may load the starter kit firmware by default/after reboot, so you will need to repeat step 3 and 4 to load the DPU firmware before running the tests.

1. Install the firmware package
    ```bash
    sudo dnf install kv260-dpu-firmware
    ```
2. Check if the firmware is detected
    ```bash
    sudo xmutil listapps
    ```
    You should see any entry for the DPU firmware (e.g. `kv260-benchmark-b4096`) in the list. If the number in the active slot is 0, this means that firmware is loaded. If the active slot is -1, this means the firmware is detected but not loaded.
3. (If applicable) Unload the firmware that is currently occupying the DPU
    ```bash
    sudo xmutil unloadapp
    ```
4. Load the DPU firmware
    ```bash
    sudo xmutil loadapp kv260-benchmark-b4096
    ```

## 5. Install Python dependencies

1. pip and venv
    ```bash
    sudo dnf install python3-pip python3-venv
    ```