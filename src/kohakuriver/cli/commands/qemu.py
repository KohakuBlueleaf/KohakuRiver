"""QEMU/KVM management commands."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from kohakuriver.cli.output import console, print_error, print_success

app = typer.Typer(help="QEMU/KVM management commands")
image_app = typer.Typer(help="VM base image management")
app.add_typer(image_app, name="image")


@app.command("check")
def check():
    """Validate QEMU/KVM setup and discover VFIO GPUs."""
    from kohakuriver.qemu.capability import (
        check_cpu_virtualization,
        check_iommu,
        check_kvm,
        check_qemu,
        check_vfio_modules,
        discover_vfio_gpus,
    )

    table = Table(title="QEMU/KVM Capability Check", show_lines=True)
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    def _status(ok: bool) -> str:
        return "[green]OK[/green]" if ok else "[red]FAIL[/red]"

    # KVM
    kvm_ok, kvm_err = check_kvm()
    table.add_row(
        "KVM",
        _status(kvm_ok),
        "/dev/kvm accessible" if kvm_ok else (kvm_err or "Unknown error"),
    )

    # CPU Virtualization
    cpu_ok, cpu_err = check_cpu_virtualization()
    if cpu_ok:
        # Detect vmx vs svm
        try:
            with open("/proc/cpuinfo") as f:
                cpuinfo = f.read()
            virt_type = "vmx" if "vmx" in cpuinfo else "svm"
        except OSError:
            virt_type = "detected"
        cpu_detail = f"{virt_type} detected"
    else:
        cpu_detail = cpu_err or "Unknown error"
    table.add_row("CPU Virt", _status(cpu_ok), cpu_detail)

    # QEMU
    qemu_ok, qemu_err = check_qemu()
    if qemu_ok:
        # Get version
        try:
            result = subprocess.run(
                ["qemu-system-x86_64", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ver_line = result.stdout.strip().split("\n")[0] if result.stdout else ""
            qemu_detail = ver_line
        except Exception:
            qemu_detail = "qemu-system-x86_64 found"
    else:
        qemu_detail = qemu_err or "Unknown error"
    table.add_row("QEMU", _status(qemu_ok), qemu_detail)

    # OVMF
    ovmf_paths = [
        "/usr/share/OVMF/OVMF_CODE.fd",
        "/usr/share/OVMF/OVMF_CODE_4M.fd",
        "/usr/share/edk2/ovmf/OVMF_CODE.fd",
        "/usr/share/qemu/OVMF_CODE.fd",
    ]
    ovmf_found = next((p for p in ovmf_paths if os.path.exists(p)), None)
    table.add_row(
        "OVMF",
        _status(ovmf_found is not None),
        ovmf_found or "Not found (apt install ovmf)",
    )

    # ISO tool
    iso_tool = shutil.which("genisoimage") or shutil.which("mkisofs")
    table.add_row(
        "ISO Tool",
        _status(iso_tool is not None),
        (
            os.path.basename(iso_tool)
            if iso_tool
            else "Not found (apt install genisoimage)"
        ),
    )

    # IOMMU
    iommu_ok, iommu_err = check_iommu()
    if iommu_ok:
        iommu_groups = Path("/sys/kernel/iommu_groups")
        group_count = len(list(iommu_groups.iterdir())) if iommu_groups.exists() else 0
        iommu_detail = f"{group_count} groups"
    else:
        iommu_detail = iommu_err or "Unknown error"
    table.add_row("IOMMU", _status(iommu_ok), iommu_detail)

    # VFIO Modules
    vfio_ok, vfio_err = check_vfio_modules()
    if vfio_ok:
        vfio_detail = "vfio, vfio_pci, vfio_iommu_type1"
    else:
        vfio_detail = vfio_err or "Unknown error"
    table.add_row("VFIO Modules", _status(vfio_ok), vfio_detail)

    # ACS Override
    from kohakuriver.qemu.capability import check_acs_override_kernel

    acs_active = check_acs_override_kernel()
    table.add_row(
        "ACS Override",
        "[green]Active[/green]" if acs_active else "[dim]Inactive[/dim]",
        (
            "pcie_acs_override in kernel cmdline"
            if acs_active
            else "Not set (GPUs in shared IOMMU groups cannot be allocated individually)"
        ),
    )

    # VFIO GPUs
    gpus = []
    if iommu_ok and vfio_ok:
        gpus = discover_vfio_gpus()
    table.add_row(
        "VFIO GPUs",
        _status(len(gpus) > 0),
        f"{len(gpus)} GPUs discovered" if gpus else "None found",
    )

    console.print(table)
    console.print()

    # GPU detail table
    if gpus:
        gpu_table = Table(title="Discovered GPUs", show_lines=True)
        gpu_table.add_column("ID", justify="right", style="bold")
        gpu_table.add_column("PCI Address")
        gpu_table.add_column("Name")
        gpu_table.add_column("Group", justify="center")
        gpu_table.add_column("Audio")
        gpu_table.add_column("IOMMU Peers")

        for gpu in gpus:
            peers_str = (
                ", ".join(gpu.iommu_group_peers) if gpu.iommu_group_peers else ""
            )
            gpu_table.add_row(
                str(gpu.gpu_id),
                gpu.pci_address,
                gpu.name,
                str(gpu.iommu_group),
                gpu.audio_pci or "",
                peers_str,
            )

        console.print(gpu_table)

    # NVIDIA driver
    from kohakuriver.qemu.capability import detect_nvidia_driver_version

    nvidia_ver = detect_nvidia_driver_version()
    if nvidia_ver:
        console.print(f"\n[bold]Host NVIDIA Driver:[/bold] {nvidia_ver}")


@app.command("acs-override")
def acs_override():
    """Disable ACS on PCI bridges/switches to split IOMMU groups.

    This allows individual GPU allocation on server hardware where GPUs
    share IOMMU groups due to PCIe switches (NVLink bridges, PLX chips).

    Requires:
    - Root privileges (setpci needs write access to PCI config space)
    - pcie_acs_override=downstream,multifunction in kernel cmdline
      (add to GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub)

    The setpci changes are volatile — they reset on reboot. Use the
    runner config VM_ACS_OVERRIDE=True to apply automatically on startup.
    """
    from kohakuriver.qemu.capability import (
        apply_acs_override,
        check_acs_override_kernel,
    )

    if not shutil.which("setpci"):
        print_error("setpci not found. Install: apt install pciutils")
        raise typer.Exit(1)

    if not check_acs_override_kernel():
        console.print(
            "[yellow]Warning:[/yellow] pcie_acs_override not found in kernel cmdline.\n"
            "The setpci changes will be applied, but IOMMU groups may not split\n"
            "without the kernel parameter. Add to /etc/default/grub:\n\n"
            '  GRUB_CMDLINE_LINUX_DEFAULT="... pcie_acs_override=downstream,multifunction"\n\n'
            "Then run: sudo update-grub && sudo reboot\n"
        )

    console.print("[bold]Disabling ACS on PCI bridges and switches...[/bold]")
    results = apply_acs_override()

    table = Table(show_lines=True)
    table.add_column("Target", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Root Ports", str(results["root_ports"]))
    table.add_row("PLX/Broadcom Switches", str(results["plx_switches"]))
    table.add_row("PCI Bridges", str(results["pci_bridges"]))
    console.print(table)

    if results["errors"]:
        for err in results["errors"]:
            console.print(f"[yellow]Warning:[/yellow] {err}")

    total = results["root_ports"] + results["plx_switches"] + results["pci_bridges"]
    if total > 0:
        print_success(f"ACS disabled on {total} devices")
        console.print(
            "\n[dim]Run 'kohakuriver qemu check' to verify GPU IOMMU groups are now split.[/dim]"
        )
    else:
        console.print("[yellow]No PCI bridges/switches found to modify.[/yellow]")


@image_app.command("create")
def image_create(
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Image name"),
    ] = "ubuntu-24.04",
    ubuntu_version: Annotated[
        str,
        typer.Option("--ubuntu-version", help="Ubuntu version"),
    ] = "24.04",
    size: Annotated[
        str,
        typer.Option("--size", "-s", help="Max virtual disk size (thin-provisioned)"),
    ] = "500G",
    images_dir: Annotated[
        str,
        typer.Option("--images-dir", help="Output directory for base images"),
    ] = "/var/lib/kohakuriver/vm-images",
    with_nvidia: Annotated[
        bool,
        typer.Option(
            "--with-nvidia", help="Auto-detect host NVIDIA driver and install in image"
        ),
    ] = False,
    nvidia_version: Annotated[
        str | None,
        typer.Option(
            "--nvidia-version", help="Override NVIDIA driver version (e.g. 550.90.07)"
        ),
    ] = None,
):
    """Create a VM base image from Ubuntu cloud image."""
    import urllib.request

    # Check dependencies
    if not shutil.which("qemu-img"):
        print_error("qemu-img not found. Install: apt install qemu-utils")
        raise typer.Exit(1)

    has_virt_customize = shutil.which("virt-customize") is not None

    output_path = os.path.join(images_dir, f"{name}.qcow2")
    cache_dir = "/tmp/kohakuriver-vm-cache"
    cached_image = os.path.join(cache_dir, f"ubuntu-{ubuntu_version}-cloudimg.img")
    cloud_image_url = (
        f"https://cloud-images.ubuntu.com/releases/{ubuntu_version}/release/"
        f"ubuntu-{ubuntu_version}-server-cloudimg-amd64.img"
    )

    # Summary
    console.print(
        Panel.fit(
            f"[bold]Image Name:[/bold] {name}\n"
            f"[bold]Ubuntu Version:[/bold] {ubuntu_version}\n"
            f"[bold]Max Disk Size:[/bold] {size} (thin-provisioned)\n"
            f"[bold]Output Path:[/bold] {output_path}\n"
            f"[bold]virt-customize:[/bold] {'available' if has_virt_customize else 'not found (image will be minimal)'}\n"
            f"[bold]NVIDIA Driver:[/bold] {'yes' if with_nvidia else 'no'}",
            title="VM Base Image Creator",
        )
    )

    # Create directories
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)

    # Download cloud image
    if not os.path.exists(cached_image):
        console.print(
            f"\n[bold]Downloading Ubuntu {ubuntu_version} cloud image...[/bold]"
        )
        console.print(f"[dim]{cloud_image_url}[/dim]")
        try:
            urllib.request.urlretrieve(cloud_image_url, cached_image)
        except Exception as e:
            print_error(f"Failed to download cloud image: {e}")
            raise typer.Exit(1)
        console.print("[green]Download complete.[/green]")
    else:
        console.print(f"\n[dim]Using cached cloud image: {cached_image}[/dim]")

    # Copy and resize
    console.print(f"\n[bold]Creating base image ({size})...[/bold]")
    try:
        shutil.copy2(cached_image, output_path)
        result = subprocess.run(
            ["qemu-img", "resize", output_path, size],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print_error(f"qemu-img resize failed: {result.stderr}")
            raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to create base image: {e}")
        raise typer.Exit(1)

    # Customize with virt-customize
    if has_virt_customize:
        console.print(
            "\n[bold]Customizing image (installing packages, enabling services)...[/bold]"
        )
        customize_cmd = [
            "virt-customize",
            "-a",
            output_path,
            "--install",
            "python3,python3-pip,openssh-server,curl,wget,net-tools,iputils-ping,cloud-init,qemu-guest-agent",
            "--run-command",
            "systemctl enable ssh",
            "--run-command",
            "systemctl enable qemu-guest-agent",
            "--run-command",
            "sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config",
            "--run-command",
            "sed -i 's/^PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config",
            "--run-command",
            "echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config.d/99-kohakuriver.conf",
            "--run-command",
            "cloud-init clean",
            "--truncate",
            "/etc/machine-id",
        ]
        result = subprocess.run(customize_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"[yellow]virt-customize warnings:[/yellow]\n{result.stderr}")
        else:
            console.print("[green]Image customization complete.[/green]")
    else:
        console.print(
            "\n[yellow]virt-customize not found. Skipping image customization.[/yellow]\n"
            "[dim]Install: apt install libguestfs-tools[/dim]"
        )

    # NVIDIA driver installation
    if with_nvidia:
        if not has_virt_customize:
            print_error(
                "--with-nvidia requires virt-customize (apt install libguestfs-tools)"
            )
            raise typer.Exit(1)

        # Detect driver version
        driver_version = nvidia_version
        if not driver_version:
            from kohakuriver.qemu.capability import detect_nvidia_driver_version

            driver_version = detect_nvidia_driver_version()
            if not driver_version:
                print_error(
                    "Could not detect NVIDIA driver version on host. "
                    "Use --nvidia-version to specify manually."
                )
                raise typer.Exit(1)
            console.print(
                f"\n[bold]Detected host NVIDIA driver:[/bold] {driver_version}"
            )

        # Resolve download URL
        driver_filename = f"NVIDIA-Linux-x86_64-{driver_version}.run"
        driver_urls = [
            f"https://us.download.nvidia.com/tesla/{driver_version}/{driver_filename}",
            f"https://us.download.nvidia.com/XFree86/Linux-x86_64/{driver_version}/{driver_filename}",
        ]

        driver_url = None
        for url in driver_urls:
            try:
                req = urllib.request.Request(url, method="HEAD")
                resp = urllib.request.urlopen(req, timeout=10)
                if resp.status == 200:
                    driver_url = url
                    break
            except Exception:
                continue

        if not driver_url:
            print_error(
                f"Could not find NVIDIA driver download for version {driver_version}. "
                f"Tried:\n  " + "\n  ".join(driver_urls)
            )
            raise typer.Exit(1)

        console.print(f"[bold]Downloading NVIDIA driver {driver_version}...[/bold]")
        console.print(f"[dim]{driver_url}[/dim]")

        driver_cache = os.path.join(cache_dir, driver_filename)
        if not os.path.exists(driver_cache):
            try:
                urllib.request.urlretrieve(driver_url, driver_cache)
            except Exception as e:
                print_error(f"Failed to download NVIDIA driver: {e}")
                raise typer.Exit(1)
        else:
            console.print(f"[dim]Using cached driver: {driver_cache}[/dim]")

        console.print(
            "[bold]Installing NVIDIA driver in image (this may take several minutes)...[/bold]"
        )
        nvidia_cmd = [
            "virt-customize",
            "-a",
            output_path,
            "--install",
            "build-essential,dkms,linux-headers-generic,pkg-config,libglvnd-dev",
            "--upload",
            f"{driver_cache}:/tmp/nvidia.run",
            "--run-command",
            "chmod +x /tmp/nvidia.run && /tmp/nvidia.run --silent --dkms --no-cc-version-check",
            "--run-command",
            "rm /tmp/nvidia.run",
        ]
        result = subprocess.run(nvidia_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(
                f"[red]NVIDIA driver installation failed:[/red]\n{result.stderr}"
            )
            console.print(
                "[yellow]The base image was created but without NVIDIA drivers.[/yellow]"
            )
        else:
            console.print(
                f"[green]NVIDIA driver {driver_version} installed successfully.[/green]"
            )

    # Summary
    try:
        result = subprocess.run(
            ["qemu-img", "info", "--output=json", output_path],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            import json

            info = json.loads(result.stdout)
            virtual_size = info.get("virtual-size", 0)
            actual_size = info.get("actual-size", 0)
            virtual_gb = virtual_size / (1024**3)
            actual_mb = actual_size / (1024**2)
            console.print(
                Panel.fit(
                    f"[bold]Path:[/bold] {output_path}\n"
                    f"[bold]Virtual Size:[/bold] {virtual_gb:.1f} GB\n"
                    f"[bold]Actual Size:[/bold] {actual_mb:.1f} MB (thin-provisioned)",
                    title="Image Created Successfully",
                    border_style="green",
                )
            )
        else:
            print_success(f"Base image created: {output_path}")
    except Exception:
        print_success(f"Base image created: {output_path}")


@image_app.command("list")
def image_list(
    images_dir: Annotated[
        str,
        typer.Option("--images-dir", help="Directory containing base images"),
    ] = "/var/lib/kohakuriver/vm-images",
):
    """List available VM base images."""
    images_path = Path(images_dir)
    if not images_path.exists():
        console.print(f"[yellow]Images directory not found: {images_dir}[/yellow]")
        console.print(f"[dim]Create it with: sudo mkdir -p {images_dir}[/dim]")
        return

    qcow2_files = sorted(images_path.glob("*.qcow2"))
    if not qcow2_files:
        console.print(f"[yellow]No .qcow2 images found in {images_dir}[/yellow]")
        console.print("[dim]Create one with: kohakuriver qemu image create[/dim]")
        return

    table = Table(title="VM Base Images", show_lines=True)
    table.add_column("Name", style="bold")
    table.add_column("Virtual Size", justify="right")
    table.add_column("Actual Size", justify="right")
    table.add_column("Modified")

    for img in qcow2_files:
        name = img.stem
        stat = img.stat()
        modified = (
            __import__("datetime")
            .datetime.fromtimestamp(stat.st_mtime)
            .strftime("%Y-%m-%d %H:%M")
        )

        # Get qemu-img info for virtual vs actual size
        virtual_size = ""
        actual_size = f"{stat.st_size / (1024**2):.1f} MB"
        try:
            result = subprocess.run(
                ["qemu-img", "info", "--output=json", str(img)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                import json

                info = json.loads(result.stdout)
                vs = info.get("virtual-size", 0)
                asz = info.get("actual-size", stat.st_size)
                virtual_size = f"{vs / (1024**3):.1f} GB"
                actual_size = f"{asz / (1024**2):.1f} MB"
        except Exception:
            pass

        table.add_row(name, virtual_size, actual_size, modified)

    console.print(table)
