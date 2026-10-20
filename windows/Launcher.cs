// SPDX-License-Identifier: MIT
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;
[assembly: AssemblyTitle("Shuangling Quota")]
[assembly: AssemblyDescription("White dragon Codex quota companion")]
[assembly: AssemblyVersion("1.1.1.0")]
internal static class Launcher {
    internal static string Quote(string argument) {
        var result = new StringBuilder("\""); int slashes = 0;
        foreach (char c in argument) {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { result.Append('\\', slashes * 2 + 1).Append(c); }
            else { result.Append('\\', slashes).Append(c); }
            slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }
    [STAThread] private static int Main(string[] args) {
        try {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string runtime = Path.Combine(root, "runtime", "pythonw.exe");
            string script = Path.Combine(root, "runtime", "launcher.py");
            if (!File.Exists(runtime) || !File.Exists(script))
                throw new FileNotFoundException("请完整解压发行包，保留 exe 旁边的 runtime 文件夹。");
            if (args.Length == 1 && args[0] == "--check") return 0;
            var command = new StringBuilder(Quote(script));
            foreach (string argument in args) command.Append(' ').Append(Quote(argument));
            var process = Process.Start(new ProcessStartInfo(runtime, command.ToString()) {
                WorkingDirectory = Environment.CurrentDirectory, UseShellExecute = false, CreateNoWindow = true
            });
            // Wait for command-line operations so build and diagnostics can check failures.
            if (args.Length > 0 && args[0] != "--watch-host") {
                process.WaitForExit(); return process.ExitCode;
            }
            return 0;
        } catch (Exception error) {
            MessageBox.Show(error.Message, "霜铃 · 无法启动", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
