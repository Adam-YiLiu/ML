# Jetson Orin Nano setup

Last version of Jetpack version tested: Jetpack 6.2.1

## 1. Flashing the OS

There are 2 options for flashing the OS on the Jetson Orin Nano:

1. **Flashing to SD Card**
    > [!IMPORTANT]
    > Newly unboxed Jetson Orin Nano devices will require a firmware update that can only be done through the NVIDIA SDK manager. For details, see the Flashing to nvme section below.
    - Download the OS image from the [NVIDIA website](https://developer.nvidia.com/embedded/jetpack-archive) and flash it to your SD card using a tool like [Balena Etcher](https://www.balena.io/etcher/).
    - Insert the flashed SD card into the Jetson Orin Nano and power it on.
    - Continue the setup process by connecting the device to a monitor and keyboard, and following the on-screen instructions to create a user account and set up Wi-Fi.
2. **Flashing to nvme**
    > [!CAUTION]
    > The host OS version matters when using the NVIDIA SDK Manager. If you cannot find the right Jetpack version, try using an older version of Ubuntu (e.g. 24.04/22.04) as the host OS.

    > [!CAUTION]
    > It is not recommended to flash from a virtual machine/WSL due to potential USB passthrough issues.
    - This requires flashing via a USB connection to a host machine using the NVIDIA SDK Manager
    - Download the NVIDIA SDK Manager from the [NVIDIA website](https://developer.nvidia.com/nvidia-sdk-manager) and follow the instructions to flash the OS image to the Jetson Orin Nano's nvme storage.