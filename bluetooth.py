import re
import subprocess
import threading

AUDIO_SINK = '0000110b-0000-1000-8000-00805f9b34fb'

class Device:
    def __init__(self, addr):
        self.addr = addr
        self.name = ''
        self.cls = 0
        self.rssi = -1000
        self.rssis = []
        self._rssisum = 0
        self._rssiidx = 0
        self.uuids = []
        self.paired = None
        self.trusted = None
        self.connected = None

    def __repr__(self):
        return 'Device({}, class={}, name={}, paired={}, trusted={}, connected={}, uuids={}, rssi={})'.format(
                repr(self.addr), hex(self.cls), repr(self.name), repr(self.paired), repr(self.trusted), repr(self.connected), repr(self.uuids), self.rssi)

    def __str__(self):
        return '{} ({}) class: {}, paired: {}, trusted: {}, connected: {}, rssi: {}'.format(
                self.addr, self.name, hex(self.cls), self.paired, self.trusted, self.connected, self.rssi)

class Scanner:
    def __init__(self, onAdded=None, onChanged=None, onRemoved=None):
        self._deesc = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|[\x01-\x07\n]*')
        self._linere = re.compile(r'^(?:(?:\[([^\]]*)\]\s*)?(# @[a-z]+|Device|Controller)\s+([0-9A-F]{2}(?::[0-9A-F]{2}){5})\s*|\t)(?:([^:]+):\s+)?(.*)$', re.S)
        self._uuidre = re.compile(r'\(([^)]+)\)$')
        self._proc = None
        self._scanning = False
        self.onAdded = onAdded
        self.onChanged = onChanged
        self.onRemoved = onRemoved

    def connect(self, dev): self._write('connect ' + self._addr(dev))
    def disconnect(self, dev): self._write('disconnect ' + self._addr(dev))
    def pair(self, dev): self._write('pair ' + self._addr(dev))
    def remove(self, dev):
        addr = self._addr(dev)
        self.devices.pop(addr, None)
        self._write('remove ' + addr)
    def trust(self, dev): self._write('trust ' + self._addr(dev))
    def untrust(self, dev): self._write('untrust ' + self._addr(dev))

    def start(self, startScan=False):
        self.devices = {}
        self._proc = subprocess.Popen(['/usr/bin/bluetoothctl'], bufsize=1, text=True, encoding='utf-8', stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self._reader = threading.Thread(target=lambda: self._readLines(), name='BluetoothScanner')
        self._reader.daemon = True
        self._reader.start()
        self._scanning = False
        self._lastDev = None
        self._write('agent on')
        self._write('pairable on')
        if startScan: self.startScan()
        else: self._write('devices')

    def stop(self):
        if self._proc:
            self.stopScan()
            self._write('quit')
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.poll()
            self._reader.join()
            self._proc = self._reader = None

    def startScan(self):
        if not self._scanning:
            self._checkRunning()
            self._scanning = True
            self._write('scan on')
            self._write('discoverable on')
            self._write('devices')

    def stopScan(self):
        if self._scanning:
            self._write('discoverable off')
            self._write('scan off')
            self._scanning = False

    def _addr(self, dev): return dev.addr if isinstance(dev, Device) else dev

    def _checkRunning(self):
        if self._proc is None: raise RuntimeError('The scanner has not been started.')

    def _processLine(self, line):
        m = self._linere.fullmatch(line)
        if m:
            cat = m.group(2)
            if cat == 'Device':
                addr = m.group(3)
                cmd = m.group(1)
                if cmd == 'DEL':
                    dev = self.devices.pop(addr, None)
                    if dev is not None and self.onRemoved is not None: self.onRemoved(self, dev)
                else:
                    dev = self.devices.get(addr)
                    chg = dev is not None
                    if dev is None:
                        self.devices[addr] = dev = Device(addr)
                        self._write('info ' + addr)
                        self._write('@added ' + addr) # we'll read @added later so we know when the 'info' output is done
                    if cmd is None: self._lastDev = dev
                    key = m.group(4)
                    if key is not None:
                        self._processProperty(dev, key, m.group(5))
                        if chg and self.onChanged is not None: self.onChanged(self, dev)
            elif cat is None and self._lastDev is not None:
                key = m.group(4)
                if key is not None: self._processProperty(self._lastDev, key, m.group(5))
            elif self.onAdded is not None and cat == '# @added':
                dev = self.devices.get(m.group(3))
                if dev is not None: self.onAdded(self, dev)
        elif line == 'Authorize service' or line == 'Request confirmation':
            self._write('yes')

    def _processProperty(self, dev, key, value):
        if key == 'Name': dev.name = value
        elif key == 'Class': dev.cls = int(value[2:], 16)
        elif key == 'Paired': dev.paired = value == 'yes'
        elif key == 'Trusted': dev.trusted = value == 'yes'
        elif key == 'Connected': dev.connected = value == 'yes'
        elif key == 'RSSI':
            rssi = int(value)
            if len(dev.rssis) == 10:
                dev._rssisum = dev._rssisum - dev.rssis[dev._rssiidx] + rssi
                dev.rssis[dev._rssiidx] = rssi
                dev._rssiidx += 1
                if dev._rssiidx == len(dev.rssis): dev._rssiidx = 0
            else:
                dev.rssis.append(rssi)
                dev._rssisum += rssi
            dev.rssi = dev._rssisum / len(dev.rssis)
        elif key == 'UUID':
            m = self._uuidre.search(value)
            if m:
                uuid = m.group(1)
                if not uuid in dev.uuids: dev.uuids.append(uuid)
        elif key == 'UUIDs':
            if not value in dev.uuids: dev.uuids.append(value)

    def _readLines(self):
        while True:
            line = self._deesc.sub('', self._proc.stdout.readline())
            if line: self._processLine(line)
            elif self._proc.poll() is not None: break
        
    def _write(self, line):
        self._checkRunning()
        self._proc.stdin.write(line)
        self._proc.stdin.write("\n")
