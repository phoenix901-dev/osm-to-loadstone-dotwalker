ar=WScript.Arguments;
if (ar.Length==0)
WScript.Quit();
o=encodeURIComponent(ar(0));
var fso = new ActiveXObject("Scripting.FileSystemObject");
var path= fso.GetAbsolutePathName("")+"\\conv\\";
rx =path+"res.txt";
if (fso.FileExists(rx)==1)
fso.DeleteFile(rx, 1);
f2 = fso.OpenTextFile(rx, 2, 1, -2);
f2.WriteLine(o);
f2.close();
