#!/usr/bin/env python3
"""Byte-preserving bluetoothd decompression for verified Intel macOS builds.

Version 1.0. No bundled Apple binary, networking, EFI writes, SIP changes,
automatic reboot, or snapshot deletion. Default command is read-only check.
"""
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

SUPPORTED = {"25G342": {
    "size": 23555568,
    "sha256": "579bb5f53d6b26d2c9b10228df357ca783d636d8dd92c21141195de5a725f23a",
}}
TARGET = Path("/usr/sbin/bluetoothd")
STATE_ROOT = Path("/var/db/bluetooth-uncompressed-repair")
BOOT_KEY = "4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:boot-path"
COMPRESSED = 0x20


class RepairError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise RepairError(message)


def command(*args):
    result = subprocess.run([str(a) for a in args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env={**os.environ, "LC_ALL": "C"})
    if result.returncode:
        raise RepairError("命令失败：" + " ".join(map(str, args)) + "\n" +
                          result.stderr.decode(errors="replace") +
                          result.stdout.decode(errors="replace"))
    return result.stdout


def disk_info(path):
    return plistlib.loads(command("/usr/sbin/diskutil", "info", "-plist", path))


def valid_uuid(value):
    try:
        return str(uuid.UUID(value)).upper()
    except (ValueError, TypeError, AttributeError):
        raise RepairError("无效的磁盘或快照 UUID")


def base_device(root):
    match = re.fullmatch(r"(disk\d+s\d+)s\d+", root.get("DeviceIdentifier", ""))
    require(root.get("APFSSnapshot") is True and match is not None,
            "只支持从 APFS 系统快照启动的 macOS；请勿在恢复模式执行本脚本。")
    return match[1]


def snapshot_list(path):
    result = plistlib.loads(command("/usr/sbin/diskutil", "apfs", "listSnapshots", "-plist", path))
    return result["Snapshots"]


def selected_snapshot(items):
    selected = [x for x in items if x.get("RootTo")]
    require(len(selected) == 1, "无法唯一确认下一次启动快照，停止。")
    return valid_uuid(selected[0]["SnapshotUUID"])


def require_snapshot(items, identity):
    matches = [x for x in items if valid_uuid(x["SnapshotUUID"]) == identity]
    require(len(matches) == 1, "所需回退/验证快照已不存在，停止。")
    return matches[0]


def environment():
    require(platform.system() == "Darwin" and platform.machine() == "x86_64",
            "仅支持 Intel x86_64 macOS；不支持 Apple Silicon。")
    build = command("/usr/bin/sw_vers", "-buildVersion").decode().strip()
    require(build in SUPPORTED, "未验证的系统构建 " + build + "，不会修改系统。支持：" + ", ".join(SUPPORTED))
    root = disk_info("/")
    device = base_device(root)
    volume = disk_info(device)
    identity = valid_uuid(volume["VolumeUUID"])
    original = valid_uuid(root["APFSSnapshotUUID"])
    return {"build": build, "root": root, "device": device,
            "volume_uuid": identity, "snapshot": original,
            "state_path": STATE_ROOT / identity / "state.json"}


def filesystem_unrestricted(status):
    return bool(re.search(r"System Integrity Protection status:\s*disabled\b", status, re.I)
                or re.search(r"Filesystem Protections:\s*disabled\b", status, re.I))


def check_security():
    auth = command("/usr/bin/csrutil", "authenticated-root", "status").decode()
    require(re.search(r"status:\s*disabled\b", auth, re.I) is not None,
            "Authenticated Root 未关闭。脚本不会自行降低系统安全设置。")
    require(filesystem_unrestricted(command("/usr/bin/csrutil", "status").decode()),
            "SIP 文件系统保护未关闭或状态无法识别。脚本不会修改 SIP。")


@contextmanager
def mounted(device, kind="apfs", snapshot=None, readonly=False):
    require(re.fullmatch(r"disk\d+s\d+", device), "无效设备编号")
    path = Path(tempfile.mkdtemp(prefix="bt-uncompress-", dir="/private/var/tmp"))
    active = False
    try:
        options = "rdonly,nobrowse" if readonly else "nobrowse"
        if snapshot:
            command("/sbin/mount_apfs", "-o", "rdonly,nobrowse", "-s", snapshot, "/dev/" + device, path)
        else:
            command("/sbin/mount", "-t", kind, "-o", options, "/dev/" + device, path)
        active = True
        yield path
    finally:
        if active:
            try:
                command("/sbin/umount", path)
            except RepairError as error:
                print("挂载点保留，需检查后卸载：" + str(path) + "\n" + str(error), file=sys.stderr)
            else:
                path.rmdir()
        else:
            path.rmdir()


def check_oc_config(path):
    config = plistlib.loads(path.read_bytes())
    require(config.get("Misc", {}).get("Security", {}).get("SecureBootModel", "").lower() == "disabled",
            "当前 OC 的 SecureBootModel 不是 Disabled，不能安全选择未封印快照。")


def check_opencore():
    """Find the actual boot ESP, inspect its config, never change it."""
    values = plistlib.loads(command("/usr/sbin/nvram", "-x", BOOT_KEY))
    path = values[BOOT_KEY]
    if isinstance(path, bytes):
        path = path.rstrip(b"\0").decode("ascii")
    match = re.search(r"HD\(\d+,GPT,([0-9a-f-]{36}),", path, re.I)
    require(match is not None and path.lower().endswith("\\efi\\oc\\opencore.efi"),
            "无法识别当前 OpenCore 的 EFI 路径，停止。")
    identity = valid_uuid(match[1])
    disks = plistlib.loads(command("/usr/sbin/diskutil", "list", "-plist"))["AllDisks"]
    matches = []
    for disk in disks:
        if not re.fullmatch(r"disk\d+s\d+", disk):
            continue
        item = disk_info(disk)
        if item.get("Content") == "EFI" and item.get("DiskUUID", "").upper() == identity:
            matches.append(item)
    require(len(matches) == 1, "无法唯一找到当前启动的 EFI 分区。")
    item = matches[0]
    if item.get("MountPoint"):
        check_oc_config(Path(item["MountPoint"]) / "EFI/OC/config.plist")
    else:
        with mounted(item["DeviceIdentifier"], kind="msdos", readonly=True) as esp:
            check_oc_config(esp / "EFI/OC/config.plist")


def verified_bytes(path, build):
    require(not path.is_symlink() and path.is_file(), "目标必须是普通文件，不能是符号链接。")
    data = path.read_bytes()
    known = SUPPORTED[build]
    require(len(data) == known["size"] and hashlib.sha256(data).hexdigest() == known["sha256"],
            "bluetoothd 与已验证的苹果原始文件不一致。可能读到了驱动修改的缓存；停止，不写入。"
            "如需重试，请先停用 BlueToolFixup/BTLEAdvFixup 并重启后重新检查，勿强行跳过校验。")
    command("/usr/bin/codesign", "--verify", "--strict",
            '-R=anchor apple and identifier "com.apple.bluetoothd"', path)
    return data


def check_permissions(path, original):
    current = path.stat()
    require(current.st_uid == original.st_uid and current.st_gid == original.st_gid
            and stat.S_IMODE(current.st_mode) == stat.S_IMODE(original.st_mode)
            and current.st_flags == original.st_flags & ~COMPRESSED,
            "写入后权限、所有者或文件标记不符合预期。")


def secure_dir(path):
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700,
            "修复记录目录必须是 root 所有的 0700 普通目录：" + str(path))


@contextmanager
def state_lock(env):
    secure_dir(STATE_ROOT)
    directory = env["state_path"].parent
    secure_dir(directory)
    fd = os.open(directory / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600,
                "不安全的锁文件")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RepairError("已有修复进程运行，请勿并发执行。")
        yield directory
    finally:
        os.close(fd)


def save_state(path, value):
    require(not path.is_symlink(), "记录文件不能是符号链接")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, prefix=".state-") as output:
        temp = Path(output.name)
        output.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
        output.flush()
        os.fsync(output.fileno())
    try:
        os.replace(temp, path)
        command("/bin/sync")
    finally:
        temp.unlink(missing_ok=True)


def read_state(env):
    path = env["state_path"]
    require(path.exists() and not path.is_symlink(), "本工具没有该系统卷的修复记录，不能自动回退。")
    info = path.stat()
    require(info.st_uid == 0 and not info.st_mode & 0o022, "修复记录权限不安全。")
    value = json.loads(path.read_text())
    require(value["volume_uuid"] == env["volume_uuid"] and value["build"] == env["build"],
            "记录与当前系统卷或系统构建不一致。")
    valid_uuid(value["original_snapshot"])
    return value


def restore_selection(mount, identity):
    require_snapshot(snapshot_list(mount), identity)
    command("/usr/sbin/bless", "--mount", mount, "--bootefi", "--snapshot", identity)
    require(selected_snapshot(snapshot_list(mount)) == identity, "未能确认回退快照已被选中。")


def verify_new_snapshot(env, items, identity):
    entry = require_snapshot(items, identity)
    with mounted(env["device"], snapshot=entry["SnapshotName"], readonly=True) as view:
        target = view / "usr/sbin/bluetoothd"
        verified_bytes(target, env["build"])
        require(not target.stat().st_flags & COMPRESSED, "新快照中的文件仍为压缩状态。")


def apply_repair(env):
    if not TARGET.stat().st_flags & COMPRESSED:
        print("当前 bluetoothd 已是未压缩状态，无需重复修复。未改动系统。")
        return
    check_security()
    check_opencore()
    require(not disk_info(env["device"]).get("MountPoint"), "底层系统卷已被挂载，可能有更新或其他补丁操作；停止。")
    with state_lock(env) as directory:
        require(not env["state_path"].exists(), "已有修复记录。请先运行 verify 或 rollback，勿重复应用。")
        with mounted(env["device"]) as mount:
            require(valid_uuid(disk_info(mount)["VolumeUUID"]) == env["volume_uuid"], "系统卷身份改变。")
            before = snapshot_list(mount)
            require_snapshot(before, env["snapshot"])
            require(selected_snapshot(before) == env["snapshot"], "存在待启动的其他快照，请先完成更新或重启。")
            version = plistlib.loads((mount / "System/Library/CoreServices/SystemVersion.plist").read_bytes())
            require(version.get("ProductBuildVersion") == env["build"], "底层系统卷构建与正在运行的系统不同。")
            target = mount / "usr/sbin/bluetoothd"
            data = verified_bytes(target, env["build"])
            require(shutil.disk_usage(mount).free >= len(data) * 4 + 64 * 1024 * 1024,
                    "APFS 可用空间不足，请至少留出约 160 MB 后重试。")
            original = target.stat()
            require(original.st_uid == 0 and original.st_gid == 0 and stat.S_IMODE(original.st_mode) == 0o755,
                    "系统程序原权限异常，停止。")
            require(original.st_flags & COMPRESSED, "底层文件已未压缩，可能有尚未完成的修复；停止。")
            backup = directory / "bluetoothd.original"
            with backup.open("xb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            backup.chmod(0o600)
            record = {"version": 1, "status": "prepared", "build": env["build"],
                      "volume_uuid": env["volume_uuid"], "original_snapshot": env["snapshot"],
                      "original_flags": original.st_flags, "original_sha256": hashlib.sha256(data).hexdigest(),
                      "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
            save_state(env["state_path"], record)
            temp = None
            changed = False
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".bluetoothd-uncompressed-", delete=False) as output:
                    temp = Path(output.name)
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.chown(temp, original.st_uid, original.st_gid)
                os.chmod(temp, stat.S_IMODE(original.st_mode))
                verified_bytes(temp, env["build"])
                require(not temp.stat().st_flags & COMPRESSED, "临时副本被压缩，停止。")
                # Record intent before the atomic replace; after interruption rollback can select the old snapshot.
                record["status"] = "replacement-started"
                save_state(env["state_path"], record)
                changed = True
                os.replace(temp, target)
                temp = None
                os.chflags(target, original.st_flags & ~COMPRESSED)
                verified_bytes(target, env["build"])
                check_permissions(target, original)
                command("/bin/sync")
                command("/usr/sbin/bless", "--folder", mount / "System/Library/CoreServices", "--bootefi", "--create-snapshot")
                after = snapshot_list(mount)
                new_id = selected_snapshot(after)
                require(new_id not in {valid_uuid(x["SnapshotUUID"]) for x in before}, "无法确认新快照。")
                require_snapshot(after, env["snapshot"])
                record["new_snapshot"] = new_id
                save_state(env["state_path"], record)
                verify_new_snapshot(env, after, new_id)
                record["status"] = "installed-reboot-required"
                save_state(env["state_path"], record)
            except BaseException:
                if changed:
                    try:
                        restore_selection(mount, env["snapshot"])
                        record["status"] = "failed-original-snapshot-selected"
                        save_state(env["state_path"], record)
                        print("修复未完成，已重新选择原启动快照。", file=sys.stderr)
                    except BaseException as error:
                        print("自动回退无法确认成功。请勿重启，保留记录并排查：" + str(error), file=sys.stderr)
                raise
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
    print("修复已写入并从新快照复核，苹果原始字节与签名保持一致。")
    print("原快照已保留。请保存工作后手动重启，再运行 verify 并实测蓝牙。")
    print("记录目录：" + str(env["state_path"].parent))


def verify(env):
    items = snapshot_list("/")
    verify_new_snapshot(env, items, env["snapshot"])
    if env["state_path"].exists():
        record = read_state(env)
        require(env["snapshot"] == record.get("new_snapshot"), "当前未从本工具创建的修复快照启动。")
    boot = re.search(r"sec = (\d+)", command("/usr/sbin/sysctl", "-n", "kern.boottime").decode())
    require(boot is not None, "无法读取启动时间")
    crashes = [p.name for p in Path("/Library/Logs/DiagnosticReports").glob("bluetoothd*.ips")
               if p.stat().st_mtime >= int(boot[1])]
    print("当前启动快照的 bluetoothd 未压缩，完整文件哈希与苹果签名通过验证。")
    print("本次启动后的蓝牙崩溃报告：" + (", ".join(crashes) if crashes else "未发现"))
    print("仍需实测持续连接、断开重连和睡眠唤醒；此工具不会启用 AirDrop。")


def rollback(env):
    with state_lock(env):
        record = read_state(env)
        old = valid_uuid(record["original_snapshot"])
        allowed = {old}
        if record.get("new_snapshot"):
            allowed.add(valid_uuid(record["new_snapshot"]))
        require(env["snapshot"] in allowed, "当前已启动其他快照，可能有后续系统改动；拒绝自动回退。")
        require(not disk_info(env["device"]).get("MountPoint"), "底层系统卷已挂载，停止。")
        with mounted(env["device"]) as mount:
            require(valid_uuid(disk_info(mount)["VolumeUUID"]) == env["volume_uuid"], "系统卷身份改变。")
            require(selected_snapshot(snapshot_list(mount)) in allowed, "另有待启动快照，拒绝覆盖。")
            restore_selection(mount, old)
        record["status"] = "rollback-selected-reboot-required"
        save_state(env["state_path"], record)
    print("已选择修复前的系统快照。保存工作后手动重启；本次去压缩修复将撤销。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="bluetoothd 去压缩修复 1.0（仅经验证的系统构建）")
    parser.add_argument("action", nargs="?", choices=["check", "apply", "verify", "rollback"], default="check")
    parser.add_argument("--yes", action="store_true", help="明确确认 apply/rollback；不能跳过兼容性检查")
    args = parser.parse_args(argv)
    env = environment()
    if args.action == "check":
        compressed = bool(TARGET.stat().st_flags & COMPRESSED)
        print("支持的系统构建：" + env["build"])
        print("自动识别的系统卷：" + env["device"] + "，卷 UUID：" + env["volume_uuid"])
        print("bluetoothd：" + ("压缩存储，可能适用本修复" if compressed else "未压缩，无需重复修复"))
        print("仅检查，未挂载或修改任何系统卷。")
        if compressed:
            check_security()
            print("正式修复前还会检查实际启动 EFI 的 SecureBootModel、原始文件签名及快照状态。")
        return
    require(os.geteuid() == 0, "此操作需要管理员身份，请使用 sudo。")
    if args.action in ("apply", "rollback"):
        require(args.yes, "该操作会改变系统启动快照。确认后添加 --yes；建议先运行 check 并备份重要数据。")
    {"apply": apply_repair, "verify": verify, "rollback": rollback}[args.action](env)


if __name__ == "__main__":
    try:
        main()
    except (RepairError, OSError, KeyError, ValueError, plistlib.InvalidFileException) as error:
        print("停止：" + str(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("已中断。若已开始写入，请查看修复记录，不要未经检查直接重启。", file=sys.stderr)
        sys.exit(130)
