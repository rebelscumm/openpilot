package main

import (
	"fmt"

	"golang.org/x/crypto/ssh"
)

func runSetup(client *ssh.Client, githubOwner, githubRepo, githubBranch string) error {
	fmt.Println("Starting setup on the device...")

	// 1. Remove existing openpilot directory
	fmt.Println("Removing existing openpilot directory...")
	if _, err := executeCommand(client, "rm -rf /data/openpilot", false); err != nil {
		return fmt.Errorf("failed to remove openpilot directory: %v", err)
	}

	// 2. Clone openpilot repository
	fmt.Println("Cloning openpilot repository...")
	cloneCmd := fmt.Sprintf("git clone -b %s --recurse-submodules --depth 1 https://github.com/%s/%s.git /data/openpilot", githubBranch, githubOwner, githubRepo)
	if _, err := executeCommand(client, cloneCmd, true); err != nil {
		return fmt.Errorf("failed to clone openpilot: %v", err)
	}

	// 3. Patch neos.json for alternate update server
	fmt.Println("Patching neos.json for alternate update server...")
	patchCmd := "sed -i 's|commadist.azureedge.net/neosupdate|op-archive.mindflakes.com/neos20|g' /data/openpilot/selfdrive/hardware/eon/neos.json"
	if _, err := executeCommand(client, patchCmd, false); err != nil {
		return fmt.Errorf("failed to patch neos.json: %v", err)
	}

	// 4. Install the vendored xps white-panda Chrysler basic firmware source.
	fmt.Println("Installing xps white-panda Chrysler basic firmware source...")
	pandaSourceCmd := "rm -rf /data/panda-xps-wp-basic && mkdir -p /data/panda-xps-wp-basic && cp -a /data/openpilot/offline_sources/panda-xps_wp_chrysler_basic/. /data/panda-xps-wp-basic/"
	if _, err := executeCommand(client, pandaSourceCmd, false); err != nil {
		return fmt.Errorf("failed to stage xps panda source: %v", err)
	}

	// 5. Build the xps white-panda firmware used by pandad.
	fmt.Println("Building xps white-panda Chrysler basic firmware...")
	buildPandaCmd := "cd /data/panda-xps-wp-basic && python3 - <<'PY'\nfrom pathlib import Path\nfor p in [Path('crypto/getcertheader.py'), Path('crypto/sign.py')]:\n    b = p.read_bytes()\n    p.write_bytes(b.replace(b'\\r\\n', b'\\n'))\nPY\ncd /data/panda-xps-wp-basic/board && mkdir -p obj && make clean && make bin"
	if _, err := executeCommand(client, buildPandaCmd, true); err != nil {
		return fmt.Errorf("failed to build xps panda firmware: %v", err)
	}

	// 6. Set advanced params used by this install.
	fmt.Println("Setting op params...")
	paramsCmd := "python3 - <<'PY'\nimport json\np='/data/op_params.json'\ntry:\n  data=json.load(open(p))\nexcept Exception:\n  data={}\ndata['steer.checkMinimum'] = False\njson.dump(data, open(p, 'w'), indent=2)\nPY"
	if _, err := executeCommand(client, paramsCmd, false); err != nil {
		return fmt.Errorf("failed to set op params: %v", err)
	}

	// 7. Normalize shell script line endings for Android.
	fmt.Println("Normalizing launch wrapper line endings...")
	normalizeCmd := "cd /data/openpilot && python3 - <<'PY'\nfrom pathlib import Path\nfor p in Path('.').rglob('*'):\n    if not p.is_file():\n        continue\n    try:\n        b = p.read_bytes()\n    except Exception:\n        continue\n    if b.startswith(b'#!') or p.suffix in {'.sh', '.py', '.bash'} or p.name in {'SConstruct', 'SConscript'}:\n        nb = b.replace(b'\\r\\n', b'\\n')\n        if nb != b:\n            p.write_bytes(nb)\nPY\nchmod 755 launch_openpilot.sh launch_chffrplus.sh launch_env.sh selfdrive/ui/spinner selfdrive/ui/ui selfdrive/sensord/sensord selfdrive/ui/soundd/soundd"
	if _, err := executeCommand(client, normalizeCmd, false); err != nil {
		return fmt.Errorf("failed to normalize launch wrappers: %v", err)
	}

	// 8. Create continue.sh script
	fmt.Println("Creating continue.sh script...")
	continueScript := `#!/usr/bin/bash\n\ncd /data/openpilot\n./launch_openpilot.sh\n`
	createScriptCmd := fmt.Sprintf(`echo $'%s' > /data/data/com.termux/files/continue.sh`, continueScript)
	if _, err := executeCommand(client, createScriptCmd, false); err != nil {
		return fmt.Errorf("failed to create continue.sh: %v", err)
	}

	// 9. Make continue.sh executable
	fmt.Println("Making continue.sh executable...")
	if _, err := executeCommand(client, "chmod +x /data/data/com.termux/files/continue.sh", false); err != nil {
		return fmt.Errorf("failed to make continue.sh executable: %v", err)
	}

	// 10. Reboot the device
	fmt.Println("Setup complete. Rebooting device...")
	if _, err := executeCommand(client, "reboot", false); err != nil {
		// The reboot command might close the connection before a response is received.
		// We can consider this a success if there's no immediate error.
		fmt.Println("Reboot command sent. The device is now restarting.")
	}

	return nil
}
