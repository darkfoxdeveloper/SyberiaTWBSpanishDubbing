using System.Security.Cryptography;
using Mono.Cecil;
using Mono.Cecil.Cil;

const string OriginalSha = "ddbe711799a764ca30fd6af40ecd14c13c0735d8a5d76ae1026f7ca628505fa7";
const string SpanishBankFolder = "Spanish(Spain)";
const int SpanishId = 3;

if (args.Length is < 2 or > 5 || File.Exists(args[1]))
    throw new ArgumentException("Indica Assembly-CSharp.dll original y una ruta de salida nueva.");

using (var input = File.OpenRead(args[0]))
{
    var hash = Convert.ToHexStringLower(SHA256.HashData(input));
    if (hash != OriginalSha)
        throw new InvalidOperationException("La DLL no coincide con la compilación de Steam comprobada.");
}

using var assembly = AssemblyDefinition.ReadAssembly(args[0]);
var localization = assembly.MainModule.GetType("localisationsystem");
var exists = localization.Methods.Single(m => m.Name == "voicelanguageexists");
var setVoice = localization.Methods.Single(m => m.Name == "setvoicelanguage");
var control = assembly.MainModule.GetType("wwisecontrol");
var getControl = control.Methods.Single(m => m.Name == "getinstance");
var setBankLanguage = control.Methods.Single(m => m.Name == "setlanguage");
var awake = control.Methods.Single(m => m.Name == "Awake");

// The stock menu already resolves the Spanish label from Articy language ID 3.
var existsIl = exists.Body.GetILProcessor();
var oldFirst = exists.Body.Instructions[0];
foreach (var instruction in new[]
{
    existsIl.Create(OpCodes.Ldarg_0),
    existsIl.Create(OpCodes.Ldc_I4_3),
    existsIl.Create(OpCodes.Bne_Un_S, oldFirst),
    existsIl.Create(OpCodes.Ldc_I4_1),
    existsIl.Create(OpCodes.Ret),
})
    existsIl.InsertBefore(oldFirst, instruction);

// The original default branch is shared by several unsupported language IDs.
var setIl = setVoice.Body.GetILProcessor();
var dispatch = setVoice.Body.Instructions.Single(i => i.OpCode == OpCodes.Switch);
var targets = (Instruction[])dispatch.Operand;
var spanish = setIl.Create(OpCodes.Call, getControl);
var defaultCase = targets[SpanishId];
setIl.Append(spanish);
setIl.Emit(OpCodes.Ldstr, SpanishBankFolder);
setIl.Emit(OpCodes.Ldstr, "_Dialog");
setIl.Emit(OpCodes.Callvirt, setBankLanguage);
setIl.Emit(OpCodes.Ret);
targets[SpanishId] = spanish;
if (targets[4] != defaultCase)
    throw new InvalidOperationException("La tabla de idiomas original no coincide.");

// Awake normally sets English. Respect Spanish if the game initialized its settings first.
var awakeIl = awake.Body.GetILProcessor();
var english = awake.Body.Instructions.Single(i => i.OpCode == OpCodes.Ldstr && (string)i.Operand == "English(US)");
var dialogMask = english.Next;
var getVoice = localization.Methods.Single(m => m.Name == "getvoicelanguage");
foreach (var instruction in new[]
{
    awakeIl.Create(OpCodes.Call, getVoice),
    awakeIl.Create(OpCodes.Ldc_I4_3),
    awakeIl.Create(OpCodes.Bne_Un_S, english),
    awakeIl.Create(OpCodes.Ldstr, SpanishBankFolder),
    awakeIl.Create(OpCodes.Br_S, dialogMask),
})
    awakeIl.InsertBefore(english, instruction);

// Expand branches in the longer Awake body to keep preexisting jumps in range.
var longBranches = new Dictionary<Code, OpCode>
{
    [Code.Br_S] = OpCodes.Br,
    [Code.Brfalse_S] = OpCodes.Brfalse,
    [Code.Brtrue_S] = OpCodes.Brtrue,
    [Code.Beq_S] = OpCodes.Beq,
    [Code.Bne_Un_S] = OpCodes.Bne_Un,
    [Code.Bge_S] = OpCodes.Bge,
    [Code.Bge_Un_S] = OpCodes.Bge_Un,
    [Code.Bgt_S] = OpCodes.Bgt,
    [Code.Bgt_Un_S] = OpCodes.Bgt_Un,
    [Code.Ble_S] = OpCodes.Ble,
    [Code.Ble_Un_S] = OpCodes.Ble_Un,
    [Code.Blt_S] = OpCodes.Blt,
    [Code.Blt_Un_S] = OpCodes.Blt_Un,
    [Code.Leave_S] = OpCodes.Leave,
};
foreach (var instruction in awake.Body.Instructions)
    if (longBranches.TryGetValue(instruction.OpCode.Code, out var expanded))
        instruction.OpCode = expanded;

var recap = args.Contains("--recap");
var ambience = args.Contains("--ambiente");
if (recap)
{
    var playRecap = assembly.MainModule.GetType("LauncherManager").Methods.Single(m => m.Name == "playpreviously");
    var name = playRecap.Body.Instructions.Single(i => i.OpCode == OpCodes.Ldstr && (string)i.Operand == "previously");
    var il = playRecap.Body.GetILProcessor();
    foreach (var instruction in new[]
    {
        il.Create(OpCodes.Call, getVoice),
        il.Create(OpCodes.Ldc_I4_3),
        il.Create(OpCodes.Bne_Un_S, name),
        il.Create(OpCodes.Ldstr, "previously-es"),
        il.Create(OpCodes.Br_S, name.Next),
    })
        il.InsertBefore(name, instruction);
}

if (ambience)
{
    var currentLanguage = assembly.MainModule.GetType("AkSoundEngine").Methods.Single(m => m.Name == "GetCurrentLanguage");
    var language = new FieldDefinition("menuSoundBankLanguage", FieldAttributes.Private | FieldAttributes.Static,
        assembly.MainModule.TypeSystem.String);
    var launcher = assembly.MainModule.GetType("LauncherManager");
    launcher.Fields.Add(language);
    var displayMenu = launcher.Methods.Single(m => m.Name == "DisplayMenu");
    var il = displayMenu.Body.GetILProcessor();
    var first = displayMenu.Body.Instructions[0];
    var load = control.Methods.Single(m => m.Name == "loadbank");
    var unload = control.Methods.Single(m => m.Name == "unloadbank");
    var compare = new MethodReference("op_Equality", assembly.MainModule.TypeSystem.Boolean,
        assembly.MainModule.TypeSystem.String);
    compare.Parameters.Add(new ParameterDefinition(assembly.MainModule.TypeSystem.String));
    compare.Parameters.Add(new ParameterDefinition(assembly.MainModule.TypeSystem.String));
    // The initial Bootstrap was loaded before the saved options. Reload it before starting menu audio.
    foreach (var instruction in new[]
    {
        il.Create(OpCodes.Call, currentLanguage),
        il.Create(OpCodes.Ldsfld, language),
        il.Create(OpCodes.Call, compare),
        il.Create(OpCodes.Brtrue_S, first),
        il.Create(OpCodes.Call, currentLanguage),
        il.Create(OpCodes.Stsfld, language),
        il.Create(OpCodes.Ldstr, "Bootstrap"),
        il.Create(OpCodes.Call, unload),
        il.Create(OpCodes.Ldstr, "Bootstrap"),
        il.Create(OpCodes.Call, load),
        il.Create(OpCodes.Pop),
    })
        il.InsertBefore(first, instruction);
}

var captureFolder = args.Skip(2).SingleOrDefault(arg => arg != "--recap" && arg != "--ambiente");
if (captureFolder is not null)
    AddCaptureProbe(assembly.MainModule, args[0], captureFolder, recap, ambience);

assembly.Write(args[1]);

static void AddCaptureProbe(ModuleDefinition module, string input, string screenshots, bool recap, bool ambience)
{
    var launcher = module.GetType("LauncherUIManager");
    var launcherManager = module.GetType("LauncherManager");
    var manager = launcher.Fields.Single(f => f.Name == "launcherManager");
    var confirmGamma = launcherManager.Methods.Single(m => m.Name == "ValidateGamma");
    var update = launcher.Methods.Single(m => m.Name == "Update");
    var il = update.Body.GetILProcessor();
    var first = update.Body.Instructions[0];
    var unity = module.AssemblyReferences.Single(r => r.Name == "UnityEngine.CoreModule");
    var time = new TypeReference("UnityEngine", "Time", module, unity);
    var frames = new MethodReference("get_frameCount", module.TypeSystem.Int32, time);
    using var screenModule = ModuleDefinition.ReadModule(Path.Combine(Path.GetDirectoryName(input)!,
        "UnityEngine.ScreenCaptureModule.dll"));
    var capture = module.ImportReference(screenModule.GetType("UnityEngine.ScreenCapture").Methods.Single(
        m => m.Name == "CaptureScreenshot" && m.Parameters.Count == 2 &&
             m.Parameters[1].ParameterType.FullName == "System.Int32"));
    var nav = module.GetType("UIOptionsTabsNavigation").Methods.Single(m => m.Name == "GoToTab");
    var tabs = launcher.Fields.Single(f => f.Name == "optionsTabsNav");
    var textLanguage = module.GetType("localisationsystem").Methods.Single(m => m.Name == "settextlanguage");
    var voiceLanguage = module.GetType("localisationsystem").Methods.Single(m => m.Name == "setvoicelanguage");
    var displayOptions = launcher.Methods.Single(m => m.Name == "DisplayOptions");
    var starter = module.GetType("UILauncherScreenStarter");
    var starterField = launcher.Fields.Single(f => f.Name == "uiLauncherScreenStarter");
    var ready = starter.Fields.Single(f => f.Name == "isCallToDisplayed");
    ready.IsAssembly = true;
    var exit = starter.Methods.Single(m => m.Name == "ExitCallTo");
    var displayMain = launcher.Methods.Single(m => m.Name == "DisplayMainMenu");
    var startFrame = new FieldDefinition("captureStartFrame", FieldAttributes.Private, module.TypeSystem.Int32);
    launcher.Fields.Add(startFrame);
    var debug = new TypeReference("UnityEngine", "Debug", module, unity);
    var log = new MethodReference("Log", module.TypeSystem.Void, debug);
    log.Parameters.Add(new ParameterDefinition(module.TypeSystem.Object));
    var currentAudio = module.GetType("AkSoundEngine").Methods.Single(m => m.Name == "GetCurrentLanguage");
    var bankLoader = module.GetType("wwisecontrol").Methods.Single(m => m.Name == "loadbank");
    var play = module.GetType("wwisecontrol").Methods.Single(m => m.Name == "playevent");
    var intro = new List<Instruction>();
    void AtFrame(int frame, params Instruction[] action)
    {
        var next = il.Create(OpCodes.Nop);
        intro.Add(il.Create(OpCodes.Call, frames));
        intro.Add(il.Create(OpCodes.Ldarg_0));
        intro.Add(il.Create(OpCodes.Ldfld, startFrame));
        intro.Add(il.Create(OpCodes.Sub));
        intro.Add(il.Create(OpCodes.Ldc_I4, frame));
        intro.Add(il.Create(OpCodes.Bne_Un, next));
        intro.AddRange(action);
        intro.Add(next);
    }
    var wait = il.Create(OpCodes.Nop);
    intro.AddRange(new[]
    {
        il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Ldfld, startFrame),
        il.Create(OpCodes.Brtrue, wait),
        il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Ldfld, manager),
        il.Create(OpCodes.Callvirt, confirmGamma),
        il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Ldfld, starterField),
        il.Create(OpCodes.Ldfld, ready), il.Create(OpCodes.Brfalse, first),
        il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Call, frames), il.Create(OpCodes.Stfld, startFrame),
        il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Ldfld, starterField),
        il.Create(OpCodes.Callvirt, exit),
        il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Call, displayMain), wait,
    });
    AtFrame(120, il.Create(OpCodes.Ldc_I4_3), il.Create(OpCodes.Call, textLanguage),
        il.Create(OpCodes.Ldc_I4_3), il.Create(OpCodes.Call, voiceLanguage),
        il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Call, displayOptions),
        il.Create(OpCodes.Ldstr, "Captura de prueba: menú abierto, idioma de voz 3."), il.Create(OpCodes.Call, log));
    AtFrame(190, il.Create(OpCodes.Call, currentAudio), il.Create(OpCodes.Call, log),
        il.Create(OpCodes.Ldstr, "Chap_1_Dialog"), il.Create(OpCodes.Call, bankLoader),
        il.Create(OpCodes.Box, module.TypeSystem.UInt32), il.Create(OpCodes.Call, log),
        il.Create(OpCodes.Ldstr, "DLG_DFr_0B53E1FE"), il.Create(OpCodes.Ldnull), il.Create(OpCodes.Call, play),
        il.Create(OpCodes.Box, module.TypeSystem.UInt32), il.Create(OpCodes.Call, log));
    for (var tab = 0; tab < 5; tab++)
    {
        AtFrame(240 + 150 * tab, il.Create(OpCodes.Ldarg_0), il.Create(OpCodes.Ldfld, tabs),
            il.Create(OpCodes.Ldc_I4, tab), il.Create(OpCodes.Callvirt, nav));
        AtFrame(350 + 150 * tab, il.Create(OpCodes.Ldstr, Path.Combine(screenshots, $"selector-{tab}.png")),
            il.Create(OpCodes.Ldc_I4_1), il.Create(OpCodes.Call, capture));
    }
    if (recap)
    {
        var playRecap = launcherManager.Methods.Single(m => m.Name == "playpreviously");
        var getTime = module.GetType("akmvideoviewer").Methods.Single(m => m.Name == "getcurrenttime");
        AtFrame(1050, il.Create(OpCodes.Call, playRecap));
        AtFrame(1350, il.Create(OpCodes.Ldstr, "Tiempo de reproducción del resumen en castellano"),
            il.Create(OpCodes.Call, log), il.Create(OpCodes.Call, getTime),
            il.Create(OpCodes.Box, getTime.ReturnType), il.Create(OpCodes.Call, log));
    }
    if (ambience)
    {
        var verify = module.GetType("wwisecontrol").Methods.Single(m => m.Name == "eventexists");
        AtFrame(200, il.Create(OpCodes.Ldstr, "Chap_6"), il.Create(OpCodes.Call, bankLoader),
            il.Create(OpCodes.Box, module.TypeSystem.UInt32), il.Create(OpCodes.Call, log),
            il.Create(OpCodes.Ldstr, "Chap_6_2D_Amb_Manager"), il.Create(OpCodes.Call, verify),
            il.Create(OpCodes.Box, module.TypeSystem.Boolean), il.Create(OpCodes.Call, log));
    }
    foreach (var instruction in intro)
        il.InsertBefore(first, instruction);
}
