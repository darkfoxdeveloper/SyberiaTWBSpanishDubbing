# Código fuente del doblaje

| Carpeta | Contenido |
| --- | --- |
| [`installer/`](installer/) | Instalador en Go para Windows x64 y Steam Deck. Comprueba la edición de Steam, reconstruye los bancos de audio, aplica el selector y permite desinstalar el parche. |
| [`selector/`](selector/) | Herramienta en C# que añade Español al selector de voces de la compilación Steam 8987614. |
| [`exporter/`](exporter/) | Exportador en Python que genera `Syberia-Castellano.zip` a partir de una instalación del juego y de las voces y datos locales del proyecto de doblaje. |

El código del repositorio se publica bajo la [licencia MIT](../LICENSE). La ilustración de Vaghen del instalador procede del material oficial de Microids y conserva su atribución original.

## Compilar los instaladores

Con Go 1.25 o posterior, ejecuta estos comandos desde `src/installer` en PowerShell. Los dos binarios se generan en `build`, en la raíz del repositorio.

```powershell
$env:GOARCH = 'amd64'
$env:CGO_ENABLED = '0'
$env:GOOS = 'windows'
go build -trimpath -o ../../build/Instalar-Syberia.exe .
$env:GOOS = 'linux'
go build -trimpath -o ../../build/Instalar-Syberia-SteamDeck .
Remove-Item Env:GOOS, Env:GOARCH, Env:CGO_ENABLED
```

Para usar los instaladores compilados, coloca el ZIP de la [Release](https://github.com/darkfoxdeveloper/SyberiaTWBSpanishDubbing/releases/latest) junto al binario correspondiente.

## Generar el selector y exportar el parche

Necesitas el SDK de .NET 9, Python 3.12 y una copia de Steam de la compilación 8987614. `dotnet` restaura la dependencia Mono.Cecil desde NuGet. Ejecuta los comandos desde la raíz del repositorio.

```powershell
$game = 'C:\ruta\a\Syberia - The World Before'
$original = Join-Path $game 'SyberiaTWB_Data\Managed\Assembly-CSharp.dll'
New-Item -ItemType Directory -Path build -Force | Out-Null
dotnet run --project src/selector/Selector.csproj -- $original build/Assembly-CSharp.modificada.dll --recap --ambiente
py -3.12 -m pip install -r src/exporter/requirements.txt
```

La entrada del selector debe ser la DLL original de Steam. Para exportar el ZIP necesitas también el catálogo `manifest_syberia.json`, la base de aprobaciones `jobs.sqlite3`, los WEM verificados y los datos suplementarios del proyecto de doblaje. Estas entradas son locales. El ZIP listo para instalar está en Releases.

```powershell
$data = 'C:\ruta\a\Syberia-Datos'
$extras = 'C:\ruta\a\datos-suplementarios'
py -3.12 src/exporter/export_patch.py $data $game build/Assembly-CSharp.modificada.dll build/Syberia-Castellano.zip `
  --longer-voices "$extras/one-liners-release" --extra $extras `
  --recap "$extras/previously-es.webm" --ambience "$extras/ambiente-doblaje"
```

- `--longer-voices` apunta a la carpeta con `one-liners.json` y los WEM de duración adaptada.
- `--extra` apunta a la carpeta con `catalogo-adicional.json` y `extra-verificado/`.
- `--recap` recibe el vídeo `previously-es.webm`.
- `--ambience` apunta a los guiones de ambiente con los WEM y registros de verificación en `render/`.
