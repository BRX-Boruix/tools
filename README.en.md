# tools

BORUIX's system tools: compile the kernel, package a bootable image, run it in a VM, and run acceptance checks.

[简体中文](README.md)

```bash
python main.py build      # compile the kernel, produce a bootable ISO
python main.py run        # start it under QEMU
python main.py br         # build and run in one step
```

## Subcommands

- `build` — compile the kernel and produce a bootable ISO
- `run` — start the ISO under QEMU; memory size (128M default) and serial output are options
- `br` — `build` plus `run`, the everyday case
- `mkimg` — create an EXT2 data disk image, volume label optional
- `limine-build` — cross-compile the bootloader's early stage
- `b3p` — build registered third-party programs and place them on the data disk

## What the bootable image contains

The ISO has two parts, the kernel and the bootloader. The kernel links twice: once to obtain the
symbol table, then again with it, because some data structure layouts depend on symbol addresses.
The bootloader is this project's fork; its early stage is built with a cross-compiler.

## The data disk

`mkimg` produces an EXT2 image with the contents of `diskfiles/`: test audio files, a sample program,
and nested directories used to verify directory traversal. The largest audio file is not committed
because of its size; provide your own if needed.

## Acceptance scripts

`checks/` holds 23 acceptance scripts, organised by domain:

- `boot` — boot sequence, system disk install, terminal creation, typing storms
- `interactive` — layer-by-layer verification with real keystrokes
- `terminal` — terminal mounting, focus, rotation, parallel instances
- `process` — batch process startup, the console service, the watchdog
- `ievents` — the input event chain
- `regression` — full self-test, interrupt response, scheduler, instruction set

The scripts only take real paths: keyboard input is injected through the VM monitor as real PS/2
scancodes, and crash detection reads actual serial output. A "pass" means the real chain worked.

## Building

Requires Python 3 and QEMU. Run `python main.py --help` for all subcommands.

## Repository layout

```
tools/
├── main.py           # the command entry point
├── tools_build/      # build and packaging implementation
├── checks/           # acceptance scripts, organised by domain
├── diskfiles/        # contents placed on the data disk
└── limine.conf       # bootloader configuration
```

## Related projects

- [`init`](https://github.com/BRX-Boruix/init) — the system init process
- [`selftest`](https://github.com/BRX-Boruix/selftest) — the system self-test program
- [`sdk`](https://github.com/BRX-Boruix/sdk) — cross-compilation tools for third-party developers

## License

MIT License, copyright Yang Borui. See [LICENSE](LICENSE).
