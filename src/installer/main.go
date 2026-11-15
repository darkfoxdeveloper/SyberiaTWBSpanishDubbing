// Apply the same Syberia voice package on Windows and SteamOS.
package main

import (
	"archive/zip"
	"bufio"
	"bytes"
	"compress/bzip2"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
)

const bankDir = "SyberiaTWB_Data/StreamingAssets/Audio/GeneratedSoundBanks/Windows"
const assemblyPath = "SyberiaTWB_Data/Managed/Assembly-CSharp.dll"
const recapDir = "SyberiaTWB_Data/StreamingAssets/videos/webm"
const englishLanguage = 0x28ccf006
const spanishLanguage = 0x0e07a43d
const sharedLanguage = 0x17705d3e
const previousReleaseAssembly = "9d9201369af6f587a570219e50117fc15433cdca2011e820fbac7f2d0e1979d0"

var (
	baseName      = regexp.MustCompile(`^[A-Za-z0-9_-]+\.(bnk|wem)$`)
	resourceName  = regexp.MustCompile(`^audio/DFr_[A-Fa-f0-9]{8}\.wem$`)
	extraResource = regexp.MustCompile(`^extra/DFr_[A-Fa-f0-9]{8}-[0-9]{1,10}\.(wem|prefetch)$`)
	ambResource   = regexp.MustCompile(`^ambiente/[A-Za-z0-9_-]+\.bnk/[0-9]{1,10}\.wem$`)
	sharedBank    = regexp.MustCompile(`^(Bootstrap|Chap_[0-9]{1,2})\.bnk$`)
	hashPattern   = regexp.MustCompile(`^[a-f0-9]{64}$`)
)

type write struct {
	Offset   int
	Size     int
	SHA256   string
	Resource string
}

type replacement struct {
	Media    uint32
	Size     int
	SHA256   string
	Resource string
}

type soundFile struct {
	Name         string
	Original     string
	Patched      string
	LanguageAt   *int `json:"language_at"`
	Writes       []write
	Replacements []replacement
	Resource     string
	ResourceSize int               `json:"resource_size"`
	SharedSource string            `json:"shared_source"`
	EventAliases map[uint32]uint32 `json:"event_aliases"`
}

type binaryFile struct {
	Original string
	Patched  string
	Size     int
}

func (file binaryFile) valid(limit int) bool {
	return file.Size > 0 && file.Size <= limit && hashPattern.MatchString(file.Original) &&
		hashPattern.MatchString(file.Patched) && file.Original != file.Patched
}

type manifest struct {
	Version             int
	Build               string
	Preview             bool
	Dialogues           int
	TotalDialogues      int `json:"total_dialogues"`
	RetainedSounds      int `json:"retained_sounds"`
	ExtraDialogues      int `json:"extra_dialogues"`
	TotalExtraDialogues int `json:"total_extra_dialogues"`
	AmbientTracks       int `json:"ambient_tracks"`
	Assembly            binaryFile
	Recap               *binaryFile
	Files               []soundFile
}

type patch struct {
	manifest
	archive map[string]*zip.File
}

func openPatch(path string) (*patch, io.Closer, error) {
	z, err := zip.OpenReader(path)
	if err != nil {
		return nil, nil, err
	}
	p := &patch{archive: make(map[string]*zip.File)}
	for _, entry := range z.File {
		if _, exists := p.archive[entry.Name]; exists {
			z.Close()
			return nil, nil, fmt.Errorf("entrada duplicada: %s", entry.Name)
		}
		p.archive[entry.Name] = entry
	}
	raw, err := p.read("manifest.json", 4<<20)
	if err == nil {
		err = json.Unmarshal(raw, &p.manifest)
	}
	if err == nil {
		err = p.validate()
	}
	if err != nil {
		z.Close()
		return nil, nil, err
	}
	return p, z, nil
}

func (p *patch) read(name string, maximum int) ([]byte, error) {
	file := p.archive[name]
	if file == nil || maximum < 1 || file.UncompressedSize64 > uint64(maximum) {
		return nil, fmt.Errorf("recurso de parche inválido: %s", name)
	}
	r, err := file.Open()
	if err != nil {
		return nil, err
	}
	defer r.Close()
	return io.ReadAll(io.LimitReader(r, int64(maximum)+1))
}

func (p *patch) validate() error {
	if p.Version < 1 || p.Version > 4 || (p.Version >= 3) != (p.Recap != nil) ||
		(p.Version == 4) != (p.AmbientTracks > 0) ||
		p.Build != "8987614" || len(p.Files) == 0 ||
		p.Dialogues <= 0 || p.Dialogues > p.TotalDialogues || (!p.Preview && p.Dialogues != p.TotalDialogues) ||
		!p.Assembly.valid(16<<20) || (p.Recap != nil && !p.Recap.valid(100<<20)) ||
		p.ExtraDialogues < 0 || p.ExtraDialogues > p.TotalExtraDialogues ||
		(!p.Preview && p.ExtraDialogues != p.TotalExtraDialogues) {
		return errors.New("manifiesto de Syberia incompatible")
	}
	files := make(map[string]bool)
	resources := make(map[string]bool)
	for _, file := range p.Files {
		name := strings.ToLower(file.Name)
		if !baseName.MatchString(file.Name) || files[name] || !hashPattern.MatchString(file.Original) ||
			!hashPattern.MatchString(file.Patched) {
			return fmt.Errorf("archivo de audio inválido: %s", file.Name)
		}
		files[name] = true
		if file.SharedSource != "" && (p.Version != 4 || !sharedBank.MatchString(file.SharedSource) ||
			file.Name != file.SharedSource || file.LanguageAt == nil) {
			return fmt.Errorf("origen de banco compartido inválido: %s", file.Name)
		}
		if len(file.EventAliases) > 0 && (p.Version != 4 || !strings.HasSuffix(name, "_dialog.bnk")) {
			return fmt.Errorf("enlace de evento inválido: %s", file.Name)
		}
		if file.LanguageAt == nil {
			if !strings.HasSuffix(name, ".wem") || len(file.Writes) != 0 || len(file.Replacements) != 0 {
				return fmt.Errorf("WEM externo inválido: %s", file.Name)
			}
			if file.Resource == "" {
				if file.Original != file.Patched {
					return fmt.Errorf("hash de WEM externo inválido: %s", file.Name)
				}
			} else if !extraResource.MatchString(file.Resource) || !strings.HasSuffix(file.Resource, ".wem") ||
				file.ResourceSize < 1 || file.ResourceSize > 16<<20 || resources[file.Resource] {
				return fmt.Errorf("reemplazo de WEM externo inválido: %s", file.Name)
			} else {
				resources[file.Resource] = true
			}
			continue
		}
		if !strings.HasSuffix(name, ".bnk") || *file.LanguageAt != 16 {
			return fmt.Errorf("cabecera de banco inválida: %s", file.Name)
		}
		end := 20
		for _, edit := range file.Writes {
			if edit.Offset < end || edit.Offset > 1<<30 || edit.Size < 1 || edit.Size > 16<<20 ||
				(!resourceName.MatchString(edit.Resource) && !extraResource.MatchString(edit.Resource)) || resources[edit.Resource] ||
				!hashPattern.MatchString(edit.SHA256) {
				return fmt.Errorf("posición de audio inválida: %s", edit.Resource)
			}
			resources[edit.Resource] = true
			end = edit.Offset + edit.Size
		}
		media := make(map[uint32]bool)
		for _, edit := range file.Replacements {
			ambient := p.Version == 4 && ambResource.MatchString(edit.Resource) &&
				edit.Resource == fmt.Sprintf("ambiente/%s/%d.wem", file.Name, edit.Media)
			if p.Version < 2 || edit.Media == 0 || media[edit.Media] || edit.Size < 1 || edit.Size > 16<<20 ||
				(!resourceName.MatchString(edit.Resource) && !extraResource.MatchString(edit.Resource) && !ambient) ||
				resources[edit.Resource] || !hashPattern.MatchString(edit.SHA256) {
				return fmt.Errorf("medio de audio inválido: %s", edit.Resource)
			}
			media[edit.Media], resources[edit.Resource] = true, true
		}
	}
	primary := 0
	extra := make(map[string]bool)
	for resource := range resources {
		if strings.HasPrefix(resource, "audio/") {
			primary++
		} else if strings.HasPrefix(resource, "extra/") {
			key, _, _ := strings.Cut(strings.TrimPrefix(resource, "extra/"), "-")
			extra[key] = true
		}
	}
	if primary != p.Dialogues || len(extra) != p.ExtraDialogues || !files["persistant_dialog.bnk"] {
		return errors.New("el inventario de voces no coincide con el parche")
	}
	return nil
}

func (file soundFile) sourcePath(english string) string {
	if file.SharedSource != "" {
		return filepath.Join(filepath.Dir(english), file.SharedSource)
	}
	return filepath.Join(english, file.Name)
}

func digest(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func fileDigest(path string) (string, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() {
		return "", fmt.Errorf("archivo no ordinario: %s", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	h := sha256.New()
	if _, err := io.Copy(h, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func checkFile(path, expected string) error {
	value, err := fileDigest(path)
	if err != nil {
		return err
	}
	if value != expected {
		return fmt.Errorf("el archivo no coincide con la versión esperada: %s", path)
	}
	return nil
}

// BSDIFF40 stores offsets as signed magnitudes and compresses three independent streams.
func offset(value []byte) int64 {
	raw := binary.LittleEndian.Uint64(value)
	magnitude := int64(raw & (1<<63 - 1))
	if raw>>63 != 0 {
		return -magnitude
	}
	return magnitude
}

func binaryDelta(original, delta []byte, expected int) ([]byte, error) {
	invalid := errors.New("diferencia binaria del parche inválida")
	if len(delta) < 32 || string(delta[:8]) != "BSDIFF40" {
		return nil, invalid
	}
	ctrlLen, diffLen, size := offset(delta[8:]), offset(delta[16:]), offset(delta[24:])
	remaining := int64(len(delta) - 32)
	if ctrlLen < 1 || ctrlLen > remaining || diffLen < 1 || diffLen > remaining-ctrlLen ||
		size != int64(expected) {
		return nil, invalid
	}
	split := 32 + ctrlLen
	ctrl := bzip2.NewReader(bytes.NewReader(delta[32:split]))
	diff := bzip2.NewReader(bytes.NewReader(delta[split : split+diffLen]))
	extra := bzip2.NewReader(bytes.NewReader(delta[split+diffLen:]))
	output := make([]byte, expected)
	var control [24]byte
	var oldPos, pos int64
	for blocks := 0; pos < size; blocks++ {
		if blocks >= 2*expected+1 {
			return nil, invalid
		}
		if _, err := io.ReadFull(ctrl, control[:]); err != nil {
			return nil, invalid
		}
		copyLen, extraLen, seek := offset(control[:]), offset(control[8:]), offset(control[16:])
		if copyLen < 0 || copyLen > size-pos || extraLen < 0 || extraLen > size-pos-copyLen ||
			(copyLen+extraLen == 0 && seek == 0) || seek < -1<<30 || seek > 1<<30 {
			return nil, invalid
		}
		run := output[pos : pos+copyLen]
		if _, err := io.ReadFull(diff, run); err != nil {
			return nil, invalid
		}
		for i := range run {
			index := oldPos + int64(i)
			if index >= 0 && index < int64(len(original)) {
				run[i] += original[index]
			}
		}
		pos += copyLen
		if _, err := io.ReadFull(extra, output[pos:pos+extraLen]); err != nil {
			return nil, invalid
		}
		pos += extraLen
		oldPos += copyLen + seek
	}
	return output, nil
}

func ensureClosed() error {
	if runtime.GOOS == "windows" {
		out, err := exec.Command("tasklist.exe", "/NH", "/FI", "IMAGENAME eq SyberiaTWB.exe").Output()
		if err != nil {
			return err
		}
		if strings.Contains(strings.ToLower(string(out)), "syberiatwb.exe") {
			return errors.New("cierra Syberia antes de instalar o desinstalar el parche")
		}
		return nil
	}
	processes, err := os.ReadDir("/proc")
	if err != nil {
		return err
	}
	for _, process := range processes {
		if !process.IsDir() {
			continue
		}
		p := filepath.Join("/proc", process.Name())
		comm, _ := os.ReadFile(filepath.Join(p, "comm"))
		cmd, _ := os.ReadFile(filepath.Join(p, "cmdline"))
		if strings.HasPrefix(strings.ToLower(string(comm)), "syberiatwb.exe") {
			return errors.New("cierra Syberia antes de instalar o desinstalar el parche")
		}
		for _, arg := range bytes.Split(cmd, []byte{0}) {
			name := filepath.Base(strings.ReplaceAll(string(arg), "\\", "/"))
			if strings.EqualFold(name, "SyberiaTWB.exe") {
				return errors.New("cierra Syberia antes de instalar o desinstalar el parche")
			}
		}
	}
	return nil
}

func writeSynced(path string, data []byte) error {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	_, writeErr := f.Write(data)
	syncErr := f.Sync()
	return errors.Join(writeErr, syncErr, f.Close())
}

func atomicFile(path string, data []byte) error {
	f, err := os.CreateTemp(filepath.Dir(path), ".syberia-dll-")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	_, writeErr := f.Write(data)
	syncErr := f.Sync()
	if err := errors.Join(writeErr, syncErr, f.Close()); err != nil {
		return err
	}
	return os.Rename(name, path)
}

func (p *patch) checkSpanish(path string) (bool, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if !info.IsDir() {
		return false, fmt.Errorf("ruta de castellano inválida: %s", path)
	}
	files, err := os.ReadDir(path)
	if err != nil {
		return false, err
	}
	if len(files) != len(p.Files) {
		return false, errors.New("la carpeta de castellano no coincide con este parche")
	}
	for _, file := range p.Files {
		if err := checkFile(filepath.Join(path, file.Name), file.Patched); err != nil {
			return false, err
		}
	}
	return true, nil
}

func (p *patch) prepareSpanish(english, staged string) error {
	for _, file := range p.Files {
		blob, err := os.ReadFile(file.sourcePath(english))
		if err != nil {
			return err
		}
		if digest(blob) != file.Original {
			return fmt.Errorf("el audio original cambió: %s", file.Name)
		}
		if file.Resource != "" {
			blob, err = p.read(file.Resource, file.ResourceSize)
			if err != nil {
				return err
			}
			if len(blob) != file.ResourceSize {
				return fmt.Errorf("WEM externo truncado: %s", file.Name)
			}
		}
		if file.LanguageAt != nil {
			pos := *file.LanguageAt
			expectedLanguage := uint32(englishLanguage)
			if file.SharedSource != "" {
				expectedLanguage = sharedLanguage
			}
			if len(blob) < pos+4 || string(blob[:4]) != "BKHD" ||
				binary.LittleEndian.Uint32(blob[pos:]) != expectedLanguage {
				return fmt.Errorf("idioma de banco inesperado: %s", file.Name)
			}
			binary.LittleEndian.PutUint32(blob[pos:], spanishLanguage)
			for _, edit := range file.Writes {
				audio, err := p.read(edit.Resource, edit.Size)
				if err != nil {
					return err
				}
				if len(audio) != edit.Size || len(blob) < edit.Offset+edit.Size || digest(audio) != edit.SHA256 {
					return fmt.Errorf("audio de parche inválido: %s", edit.Resource)
				}
				copy(blob[edit.Offset:], audio)
			}
			if len(file.Replacements) != 0 {
				replacements := make(map[uint32][]byte)
				for _, edit := range file.Replacements {
					audio, err := p.read(edit.Resource, edit.Size)
					if err != nil {
						return err
					}
					if len(audio) != edit.Size || digest(audio) != edit.SHA256 {
						return fmt.Errorf("audio de parche inválido: %s", edit.Resource)
					}
					replacements[edit.Media] = audio
				}
				blob, err = rebuildBank(blob, replacements)
				if err != nil {
					return fmt.Errorf("%s: %w", file.Name, err)
				}
			}
			if len(file.EventAliases) != 0 {
				if err := replaceEventIDs(blob, file.EventAliases); err != nil {
					return err
				}
			}
		}
		if digest(blob) != file.Patched {
			return fmt.Errorf("banco generado incorrecto: %s", file.Name)
		}
		if err := writeSynced(filepath.Join(staged, file.Name), blob); err != nil {
			return err
		}
	}
	return nil
}

func (p *patch) apply(game, action string, progress func(string)) error {
	game, err := filepath.EvalSymlinks(game)
	if err != nil {
		return err
	}
	if _, err := os.Stat(filepath.Join(game, "SyberiaTWB.exe")); err != nil {
		return errors.New("elige la carpeta que contiene SyberiaTWB.exe")
	}
	if action != "estado" {
		if err := ensureClosed(); err != nil {
			return err
		}
	}
	lock := filepath.Join(game, ".syberia-doblaje.lock")
	guard, err := os.OpenFile(lock, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return fmt.Errorf("no se pudo reservar la instalación: %w", err)
	}
	defer os.Remove(lock)
	if err := guard.Close(); err != nil {
		return err
	}

	assembly := filepath.Join(game, filepath.FromSlash(assemblyPath))
	backup := filepath.Join(filepath.Dir(assembly), "Assembly-CSharp.sin-doblaje.dll.bak")
	bankRoot := filepath.Join(game, filepath.FromSlash(bankDir))
	for _, path := range []string{filepath.Dir(assembly), bankRoot} {
		resolved, err := filepath.EvalSymlinks(path)
		if err != nil {
			return err
		}
		if filepath.Clean(resolved) != path && (runtime.GOOS != "windows" || !strings.EqualFold(resolved, path)) {
			return fmt.Errorf("la carpeta del juego apunta a una ubicación distinta: %s", path)
		}
	}
	english, spanish := filepath.Join(bankRoot, "English(US)"), filepath.Join(bankRoot, "Spanish(Spain)")
	current, err := fileDigest(assembly)
	if err != nil {
		return err
	}
	installed := current == p.Assembly.Patched
	if p.Version == 4 && current == previousReleaseAssembly {
		return errors.New("desinstala la edición anterior con su instalador antes de instalar esta versión")
	}
	if !installed && current != p.Assembly.Original {
		return errors.New("la DLL del juego no coincide con la compilación Steam 8987614 o tiene otro mod")
	}
	spanishReady, err := p.checkSpanish(spanish)
	if err != nil {
		return err
	}
	recapPath := filepath.Join(game, filepath.FromSlash(recapDir), "previously-es.webm")
	recapReady := p.Recap == nil
	if p.Recap != nil {
		folder := filepath.Dir(recapPath)
		resolved, err := filepath.EvalSymlinks(folder)
		if err != nil {
			return err
		}
		if filepath.Clean(resolved) != folder && (runtime.GOOS != "windows" || !strings.EqualFold(resolved, folder)) {
			return fmt.Errorf("la carpeta de vídeos apunta a otra ubicación: %s", folder)
		}
		if _, err := os.Lstat(recapPath); err == nil {
			if err := checkFile(recapPath, p.Recap.Patched); err != nil {
				return err
			}
			recapReady = true
		} else if !errors.Is(err, fs.ErrNotExist) {
			return err
		}
	}
	if action == "estado" {
		switch {
		case installed && spanishReady && recapReady:
			progress("Doblaje instalado. En el juego, elige Español en el idioma de las voces.")
		case installed || spanishReady:
			progress("Instalación incompleta. Pulsa Instalar para completarla.")
		default:
			progress("Instalación de Steam detectada. El doblaje está listo para instalar.")
		}
		return nil
	}
	if installed {
		if err := checkFile(backup, p.Assembly.Original); err != nil {
			return err
		}
	}
	if action == "desinstalar" {
		if installed {
			original, err := os.ReadFile(backup)
			if err != nil {
				return err
			}
			if digest(original) != p.Assembly.Original {
				return errors.New("la copia original de la DLL cambió")
			}
			if err := ensureClosed(); err != nil {
				return err
			}
			if err := atomicFile(assembly, original); err != nil {
				return err
			}
			if err := checkFile(assembly, p.Assembly.Original); err != nil {
				return err
			}
		}
		if spanishReady {
			removed, err := os.MkdirTemp(bankRoot, ".syberia-retirar-")
			if err != nil {
				return err
			}
			defer os.RemoveAll(removed)
			if err := os.Rename(spanish, filepath.Join(removed, "bancos")); err != nil {
				return err
			}
		}
		if p.Recap != nil && recapReady {
			if err := os.Remove(recapPath); err != nil {
				return err
			}
		}
		progress("Doblaje desinstalado.")
		return nil
	}

	progress("Comprobando los archivos de Steam…")
	for _, file := range p.Files {
		if err := checkFile(file.sourcePath(english), file.Original); err != nil {
			return err
		}
	}
	if !recapReady {
		progress("Preparando el vídeo «Anteriormente»…")
		if err := p.installRecap(recapPath); err != nil {
			return err
		}
	}
	if !installed {
		original, err := os.ReadFile(assembly)
		if err != nil {
			return err
		}
		if digest(original) != p.Assembly.Original {
			return errors.New("la DLL original cambió")
		}
		delta, err := p.read("selector.bsdiff", 4<<20)
		if err != nil {
			return err
		}
		modified, err := binaryDelta(original, delta, p.Assembly.Size)
		if err != nil {
			return err
		}
		if digest(modified) != p.Assembly.Patched {
			return errors.New("la DLL modificada no supera la verificación")
		}
		if _, err := os.Lstat(backup); errors.Is(err, fs.ErrNotExist) {
			if err := atomicFile(backup, original); err != nil {
				return err
			}
		} else if err != nil {
			return err
		}
		if err := checkFile(backup, p.Assembly.Original); err != nil {
			return err
		}
		if err := p.installBanks(bankRoot, english, spanish, spanishReady); err != nil {
			return err
		}
		if err := ensureClosed(); err != nil {
			return err
		}
		if err := checkFile(assembly, p.Assembly.Original); err != nil {
			return err
		}
		if err := atomicFile(assembly, modified); err != nil {
			return err
		}
		if err := checkFile(assembly, p.Assembly.Patched); err != nil {
			return err
		}
	} else if err := p.installBanks(bankRoot, english, spanish, spanishReady); err != nil {
		return err
	}
	progress("Doblaje instalado. En el juego, elige Español en el idioma de las voces.")
	return nil
}

func (p *patch) installRecap(path string) error {
	original, err := os.ReadFile(filepath.Join(filepath.Dir(path), "previously.webm"))
	if err != nil {
		return err
	}
	if digest(original) != p.Recap.Original {
		return errors.New("el vídeo original no coincide con la compilación de Steam")
	}
	delta, err := p.read("recap.bsdiff", 100<<20)
	if err != nil {
		return err
	}
	modified, err := binaryDelta(original, delta, p.Recap.Size)
	if err != nil {
		return err
	}
	if digest(modified) != p.Recap.Patched {
		return errors.New("el vídeo en castellano no supera la verificación")
	}
	if err := atomicFile(path, modified); err != nil {
		return err
	}
	return checkFile(path, p.Recap.Patched)
}

func (p *patch) installBanks(root, english, spanish string, ready bool) error {
	if ready {
		return nil
	}
	stage, err := os.MkdirTemp(root, ".syberia-bancos-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(stage)
	if err := p.prepareSpanish(english, stage); err != nil {
		return err
	}
	if err := ensureClosed(); err != nil {
		return err
	}
	if err := os.Rename(stage, spanish); err != nil {
		return err
	}
	_, err = p.checkSpanish(spanish)
	return err
}

func run(args []string) error {
	if len(args) == 1 {
		return showInstaller(nil)
	}
	if args[1] == "interfaz" {
		return showInstaller(args[2:])
	}
	if len(args) < 2 || len(args) > 4 ||
		(args[1] != "instalar" && args[1] != "desinstalar" && args[1] != "estado") {
		return errors.New("uso: instalador-syberia instalar|desinstalar|estado [carpeta-del-juego] [paquete]")
	}
	var game string
	if len(args) >= 3 {
		game = args[2]
	} else {
		fmt.Print("Ruta de la carpeta que contiene SyberiaTWB.exe: ")
		value, err := bufio.NewReader(os.Stdin).ReadString('\n')
		if err != nil && !errors.Is(err, io.EOF) {
			return err
		}
		game = strings.Trim(strings.TrimSpace(value), "\"")
	}
	if game == "" {
		return errors.New("falta la carpeta del juego")
	}
	game, err := filepath.Abs(game)
	if err != nil {
		return err
	}
	location, err := os.Executable()
	if err != nil {
		return err
	}
	bundle := filepath.Join(filepath.Dir(location), "Syberia-Castellano.zip")
	if len(args) == 4 {
		bundle = args[3]
	}
	p, closer, err := openPatch(bundle)
	if err != nil {
		return err
	}
	defer closer.Close()
	return p.apply(game, args[1], func(message string) { fmt.Println(message) })
}

func main() {
	if err := run(os.Args); err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		os.Exit(1)
	}
}
