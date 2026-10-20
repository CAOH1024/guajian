// SPDX-License-Identifier: MIT
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading.Tasks;
using System.Windows.Forms;
[assembly: AssemblyTitle("Shuangling Quota Setup")]
[assembly: AssemblyVersion("1.1.1.0")]
internal sealed class Setup : Form {
    readonly TextBox destination = new TextBox();
    readonly CheckBox shortcut = new CheckBox { Text = "创建桌面快捷方式", Checked = true, AutoSize = true };
    readonly CheckBox follow = new CheckBox { Text = "随 Codex / ChatGPT 窗口自动启停", Checked = false, AutoSize = true };
    readonly Button install = new Button { Text = "安装并启动", AutoSize = true };
    readonly Label status = new Label { Text = "无需管理员权限。需要本机 Codex CLI 已登录。", AutoSize = true };
    Setup() {
        Text = "霜铃 · Codex 额度挂件 1.1.1";
        Font = new Font("Microsoft YaHei UI", 9F); BackColor = Color.FromArgb(255,253,253);
        ForeColor = Color.FromArgb(65,55,79); ClientSize = new Size(570,310);
        FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; StartPosition = FormStartPosition.CenterScreen;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(22), ColumnCount = 1, RowCount = 7 };
        layout.Controls.Add(new Label { Text = "白色龙娘 · Codex 套餐额度挂件", AutoSize = true, Font = new Font(Font.FontFamily, 15F, FontStyle.Bold) });
        layout.Controls.Add(new Label { Text = "安装到：", AutoSize = true });
        var row = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, AutoSize = true };
        row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100)); row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        destination.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Programs","ShuanglingQuota");
        destination.Dock = DockStyle.Fill; row.Controls.Add(destination);
        var browse = new Button { Text = "浏览…", AutoSize = true };
        browse.Click += delegate { using (var dialog = new FolderBrowserDialog()) {
            dialog.SelectedPath = destination.Text;
            if (dialog.ShowDialog(this) == DialogResult.OK) destination.Text = dialog.SelectedPath;
        }};
        row.Controls.Add(browse); layout.Controls.Add(row);
        layout.Controls.Add(shortcut); layout.Controls.Add(follow); layout.Controls.Add(status); layout.Controls.Add(install);
        Controls.Add(layout); install.Click += InstallClicked;
    }
    static void Extract(string directory) {
        string root = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        Directory.CreateDirectory(root);
        using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip")) {
            if (stream == null) throw new InvalidDataException("安装数据缺失。");
            using (var archive = new ZipArchive(stream,ZipArchiveMode.Read)) {
                foreach (var entry in archive.Entries) {
                    string target = Path.GetFullPath(Path.Combine(root,entry.FullName));
                    if (Path.IsPathRooted(entry.FullName) || !target.StartsWith(root,StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("安装包包含无效路径。");
                    if (entry.Name.Length == 0) { Directory.CreateDirectory(target); continue; }
                    Directory.CreateDirectory(Path.GetDirectoryName(target)); entry.ExtractToFile(target,true);
                }
            }
        }
    }
    async void InstallClicked(object sender,EventArgs args) {
        install.Enabled = false; destination.Enabled = false; status.Text = "正在安装，请稍候…";
        try {
            string root = Path.GetFullPath(destination.Text);
            await Task.Run(delegate { Extract(root); });
            string executable = Path.Combine(root,"ShuanglingQuota.exe");
            if (shortcut.Checked) {
                Type type = Type.GetTypeFromProgID("WScript.Shell");
                object shell = Activator.CreateInstance(type);
                object link = type.InvokeMember("CreateShortcut",BindingFlags.InvokeMethod,null,shell,new object[] {
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"霜铃额度挂件.lnk") });
                Type linkType = link.GetType();
                linkType.InvokeMember("TargetPath",BindingFlags.SetProperty,null,link,new object[]{executable});
                linkType.InvokeMember("WorkingDirectory",BindingFlags.SetProperty,null,link,new object[]{root});
                linkType.InvokeMember("Save",BindingFlags.InvokeMethod,null,link,null);
            }
            Process.Start(new ProcessStartInfo(executable,follow.Checked ? "--install-autostart" : "") { WorkingDirectory = root });
            status.Text = "安装完成。可使用右上角 ··· 调整大小，右键设置自动跟随。";
            install.Text = "完成"; install.Enabled = true; install.Click -= InstallClicked; install.Click += delegate { Close(); };
        } catch (Exception error) {
            status.Text = "安装未完成。"; install.Enabled = true; destination.Enabled = true;
            MessageBox.Show(this,error.Message,"安装失败",MessageBoxButtons.OK,MessageBoxIcon.Error);
        }
    }
    [STAThread] static int Main(string[] args) {
        try {
            if (args.Length == 2 && args[0] == "--extract") { Extract(args[1]); return 0; }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            using (var form = new Setup()) {
                if (args.Length == 2 && args[0] == "--render-preview") {
                    form.Show(); Application.DoEvents();
                    using (var image = new Bitmap(form.Width,form.Height)) { form.DrawToBitmap(image,new Rectangle(Point.Empty,form.Size)); image.Save(args[1]); }
                    return 0;
                }
                Application.Run(form);
            }
            return 0;
        } catch (Exception error) {
            if (args.Length == 2 && args[0] == "--extract") {
                File.WriteAllText(Path.Combine(Path.GetDirectoryName(Path.GetFullPath(args[1])),"setup-error.log"),error.ToString());
            } else MessageBox.Show(error.Message,"霜铃安装",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}
