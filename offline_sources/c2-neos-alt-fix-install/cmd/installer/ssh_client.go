package main

import (
	"fmt"
	"os"
	"path/filepath"

	"golang.org/x/crypto/ssh"
)

func connect(ipAddress string) (*ssh.Client, error) {
	authMethods, keyMessages := loadAuthMethods()
	if len(authMethods) == 0 {
		return nil, fmt.Errorf("no usable SSH private keys found:\n%s", keyMessages)
	}

	config := &ssh.ClientConfig{
		User:            "comma",
		Auth:            authMethods,
		HostKeyCallback: ssh.InsecureIgnoreHostKey(),
	}

	client, err := ssh.Dial("tcp", ipAddress+":22", config)
	if err != nil {
		return nil, fmt.Errorf("unable to connect: %v\n\nSSH keys checked:\n%s", err, keyMessages)
	}

	return client, nil
}

func loadAuthMethods() ([]ssh.AuthMethod, string) {
	var signers []ssh.Signer
	var messages string

	if signer, err := ssh.ParsePrivateKey(privateKey); err == nil {
		signers = append(signers, signer)
		messages += "- bundled installer key: loaded\n"
	} else {
		messages += fmt.Sprintf("- bundled installer key: %v\n", err)
	}

	home, err := os.UserHomeDir()
	if err != nil {
		messages += fmt.Sprintf("- local SSH keys: unable to find home directory: %v\n", err)
	} else {
		for _, name := range []string{"id_ed25519", "id_ecdsa", "id_rsa"} {
			path := filepath.Join(home, ".ssh", name)
			key, err := os.ReadFile(path)
			if err != nil {
				messages += fmt.Sprintf("- %s: not found\n", path)
				continue
			}

			signer, err := ssh.ParsePrivateKey(key)
			if err != nil {
				messages += fmt.Sprintf("- %s: %v\n", path, err)
				continue
			}

			signers = append(signers, signer)
			messages += fmt.Sprintf("- %s: loaded\n", path)
		}
	}

	if len(signers) == 0 {
		return nil, messages
	}

	return []ssh.AuthMethod{ssh.PublicKeys(signers...)}, messages
}

func executeCommand(client *ssh.Client, command string, streamOutput bool) (string, error) {
	session, err := client.NewSession()
	if err != nil {
		return "", fmt.Errorf("failed to create session: %v", err)
	}
	defer session.Close()

	if streamOutput {
		session.Stdout = os.Stdout
		session.Stderr = os.Stderr
		err = session.Run(command)
		if err != nil {
			return "", fmt.Errorf("failed to run command with streaming: %v", err)
		}
		return "", nil
	}

	output, err := session.CombinedOutput(command)
	if err != nil {
		return "", fmt.Errorf("failed to run command: %v\nOutput: %s", err, output)
	}

	return string(output), nil
}
