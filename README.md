# Alienware x14 R1 — macOS Tahoe 26.7.3

OpenCore EFI for Alienware x14 R1 running macOS Tahoe 26.7.3.

这是针对 **macOS 26.7.3（25G342）** 的 `EFI/OC` 配置，使用 Intel AX211、SMBIOS `MacBookPro16,2` 和 OpenCore **1.0.9 DEBUG**（`DBG-109-2026-11-08`）。

## 阶段 1：原始 OC

来自 2026-11-15 本次蓝牙去压缩修复前的备份。公开版本仅清除了个人机器标识和当前系统不使用的配置条目，其余保留原配置与二进制文件。

| 组件 | 版本 |
| --- | --- |
| Lilu | 1.7.3 |
| IntelBluetoothFirmware | 2.5.3 |
| IntelBTPatcher | 2.5.3 |
| BlueToolFixup | 2.7.2 |
| AirportItlwm | 2.4.0 |

此阶段蓝牙曾出现 `bluetoothd` 崩溃及 APFS 压缩页面校验错误，尚未应用系统卷修复，也未启用 AirDrop 驱动。

## 使用前

- `PlatformInfo → Generic` 的 `SystemSerialNumber`、`MLB`、`SystemUUID` 已清空，`ROM` 已置零。请为自己的机器生成并填写，不能直接沿用他人的标识。
- 本仓库只包含 `EFI/OC`，不是完整启动盘；现有 EFI 还需匹配的 `EFI/BOOT/BOOTx64.efi`。先备份自己的 EFI，保留其他系统的启动目录。
- ACPI、USB、图形及其他硬件配置针对本机。同型号的不同硬件配置也应单独检查；不将未实测的功能标为正常。

第三方组件版权归各原作者。主要上游：[OpenCore](https://github.com/acidanthera/OpenCorePkg)、[Lilu](https://github.com/acidanthera/Lilu)、[BlueToolFixup](https://github.com/acidanthera/BrcmPatchRAM)、[IntelBluetoothFirmware](https://github.com/lshbluesky/IntelBluetoothFirmware)、[AirportItlwm](https://github.com/laobamac/itlwm)。
