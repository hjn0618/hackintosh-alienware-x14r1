# Alienware x14 R1 — macOS Tahoe 26.7.3

OpenCore EFI for Alienware x14 R1 running macOS Tahoe 26.7.3.

这是针对 **macOS 26.7.3（25G342）** 的 `EFI/OC` 配置，使用 Intel AX211、SMBIOS `MacBookPro16,2` 和 OpenCore **1.0.9 DEBUG**（`DBG-109-2026-11-08`）。

## 阶段 3：启用 AirDrop

本机已在完成蓝牙系统卷修复后，实测 **手机 → 电脑、电脑 → 手机** 的 AirDrop 文件传输成功。蓝牙连接已恢复；长期运行及完整睡眠唤醒测试尚未完成。

| 组件 | 版本 |
| --- | --- |
| Lilu | 1.7.3 |
| IntelBluetoothFirmware | 2.5.3 |
| BlueToolFixup | 2.7.2 |
| BTLEAdvFixup | 0.9.1 |
| ForbiddenItlwm | 0.5.4-beta.2 |

本阶段使用 ForbiddenItlwm 替代 AirportItlwm，使用 BTLEAdvFixup 替代 IntelBTPatcher，并配置该版本要求的 AWDL 启动参数。为保持当前系统文件最小化，已移除这两个旧驱动及不适用于当前内核的条目。**不要同时启用 IntelBTPatcher 与 BTLEAdvFixup。**

历史按三个 commit 保留：原始 OC → 蓝牙系统卷修复工具（OC 不变）→ AirDrop 配置。第二阶段不是通过更换驱动完成修复。

### 修复方法

BlueToolFixup 的内存补丁与 `bluetoothd` 的 APFS 压缩页面校验发生冲突，引起 `SIGBUS / KERN_MEMORY_ERROR`。本机已用原始字节和补丁字节精确复现内核日志中的两组哈希。

脚本把目标电脑自己的 `/usr/sbin/bluetoothd` 以未压缩形式重新存储，保持原始程序内容、苹果签名和权限，创建未封印启动快照，并保留原快照供回退。**仅复制 OC 不包含此修复。** 本机修复后蓝牙已恢复，其他电脑仍需实测。

需要 Python 3.9+、Intel macOS **25G342**、已关闭 Authenticated Root 与 SIP 文件系统保护，且实际启动 OC 的 `SecureBootModel` 为 `Disabled`。脚本会检查条件，不会自动修改安全设置或重启。先备份重要数据，关闭其他系统更新及补丁工具。

```sh
python3 scripts/bt_uncompress.py check
sudo python3 scripts/bt_uncompress.py apply --yes
# 保存工作、手动重启后验证
sudo python3 scripts/bt_uncompress.py verify
```

回退使用 `sudo python3 scripts/bt_uncompress.py rollback --yes`，再手动重启。回退选择整个修复前的系统卷快照；后续系统构建或快照已经变化、原快照丢失时会拒绝自动回退。脚本不捆绑苹果系统程序或本机 UUID，已有未压缩文件会跳过重复修复。

系统更新或重装后需重新检查。工具只支持已验证的 25G342，不能把旧版系统程序用于新系统。按驱动项目的要求，macOS 更新前先移除 `-btleadv` 并重启一次。

### AirDrop 验证

先完成上述蓝牙修复，再使用本阶段的 OC。两台设备开启 Wi-Fi、蓝牙，并临时将 AirDrop 接收设为“所有人”，分别测试小文件和较大文件的双向传输。能发现设备不代表文件传输已经正常。该驱动仍为 beta；本机成功结果不等于其他配置或系统版本均可用。

## 使用前

- `PlatformInfo → Generic` 的 `SystemSerialNumber`、`MLB`、`SystemUUID` 已清空，`ROM` 已置零。请为自己的机器生成并填写，不能直接沿用他人的标识。
- 本仓库只包含 `EFI/OC`，不是完整启动盘；现有 EFI 还需匹配的 `EFI/BOOT/BOOTx64.efi`。先备份自己的 EFI，保留其他系统的启动目录。
- ACPI、USB、图形及其他硬件配置针对本机。同型号的不同硬件配置也应单独检查；不将未实测的功能标为正常。

第三方组件版权归各原作者。主要上游：[OpenCore](https://github.com/acidanthera/OpenCorePkg)、[Lilu](https://github.com/acidanthera/Lilu)、[BlueToolFixup](https://github.com/acidanthera/BrcmPatchRAM)、[IntelBluetoothFirmware](https://github.com/lshbluesky/IntelBluetoothFirmware)、[ForbiddenItlwm / BTLEAdvFixup](https://github.com/retropineaple/ForbiddenItlwm/releases/tag/v0.5.4-beta.2)。
