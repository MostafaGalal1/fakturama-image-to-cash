#!/bin/zsh
# Builds probe.jar (the agent) and attach.jar with a JDK 17 (Fakturama 2.2 runs on Java 17).
set -e
cd "${0:A:h}"
rm -rf build && mkdir -p build/probe build/attach
javac --release 17 -d build/probe Probe.java
printf 'Agent-Class: Probe\n' > build/manifest.txt
jar --create --file build/probe.jar --manifest build/manifest.txt -C build/probe .
javac --release 17 -d build/attach Attach.java
jar --create --file build/attach.jar -C build/attach .
echo "built build/probe.jar and build/attach.jar"
