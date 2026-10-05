'VBScript
Set fso =CreateObject("Scripting.FileSystemObject")
path= fso.GetAbsolutePathName("")
'проверка наличия data.osm
f=path+"\\"+"\\in\\data.osm"
if fso.FileExists(f)=False then
msgbox "В папке IN отсутвствует входной файл DATA.OSM"
WScript.Quit()
End If
''проверка формата
set f1 = fso.OpenTextFile(f, 1, 0, -2)
s =f1.ReadLine()
s1="<?xml version='1.0' encoding='UTF-8'?>"
if s<>s1 then
'msgbox "Неправильный формат файла DATA.OSM"
'f1.close
'WScript.quit
end if
'конвертация в LoadStone
if instr(path," ")<>0 then
msgbox "Переименуйте основную папку, чтобы в имени не было пробелов."
WScript.quit
end if
set WshShell = WScript.CreateObject("WScript.Shell")
st=path+"\conv\osm.exe -u -f -m alexandrsokolov@yandex.ru "+path+"\in\data.osm "+path+"\out\data.txt"
WshShell.Run st,1,true
'подготовка к замене выражений
path= fso.GetAbsolutePathName("")+"\\"
'проверяем наличие входного файла: data.txt
infile=path+"\\out\\"+"data.txt"
if fso.FileExists(infile )=False then
'MsgBox "Ошибка конвертации."&vbcrlf&"Такое случается с данными с  сайта GisLab.ru ."&vbcrlf&"Попробуйте другой исходный файл DATA.OSM ."
WScript.Quit()
End If
'проверяем наличие файла замен:ReplaceListWord.txt
rf=path+"\\conv\\"+"ReplaceListWord.txt"
if fso.FileExists(rf)=False then
r=1
MsgBox "Отсутствует файл замены выражений."&vbcrlf&"Обработка будет произведена без замен."
'WScript.Quit()
End If
'проверяем наличие  конечного файла: out.txt
outfile =path+"\\out\\"+"out.txt"
if fso.FileExists(outfile)=True then
fso.DeleteFile outfile, 1
End If
'открываеем входные файлы
set f1 = fso.OpenTextFile(infile , 1, 0, -2)
if r<>1 then
set f3 = fso.OpenTextFile(rf, 1, 0, -2)
end if
'Создаем с открытием выходной файл
set f2 = fso.OpenTextFile(outfile, 8, 1, -2)
'обработка
s =f1.ReadAll() 'считываем сразу весь входной файл в текстовую переменную
if r<>1 then
s1 =f3.ReadAll() 'тоже с файлом :ReplaceListWord.txt
ar=Split(s1,vbNewLine) 'разбиваем выражения замен на строки
j=UBound(ar) 'определяем количество выражений для замен
for i=0 to j-1

if instr(ar(i),"=")<>0 then
ar1=Split(ar(i),"=") 'разбиваем на "что заменить" и на "чем заменить"
s=replace(s,ar1(0),ar1(1)) 'собственно замена, последняя цифра 1 означает - без учета регистра
end if
next
end if
f2.Write(s) 'записываем результат
'Закрываем файлы
f1.close
f2.close
if r<>1 then
f3.close
end if
'конвертация в DotWalker
path=fso.GetAbsolutePathName("")+"\\out\\"
ox=path+"out.txt"
'Наличие route.xml
rx =path+"route.xml"
rdat =path+"route.dat"
if fso.FileExists(rx)=True then
fso.DeleteFile rx,1
end if
if fso.FileExists(rdat)=True then
fso.DeleteFile rdat,1
end if
set f1=fso.OpenTextFile(ox, 1, 0, -2)
set f2 = fso.OpenTextFile(rx, 2, 1, -2)
set f4 = fso.OpenTextFile(rdat, 2, 1, -2)
' Первая строка выходного файла
f2.Write("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><Route>"&vbcrlf)
' Перебор строк входного файла
n=0
ar1=split(f1.readAll(),vblf)
for i=3 to UBound(ar1)-2
txt2=ar1(i)
if mid(txt2,1,1)="""" then
sd=len(txt2)
stn=mid(txt2,2,sd)
if instr(stn,"""")<>0 then
ar=split(txt2,""",")
if UBound(ar)=1 then
nm ="<Title>"&mid(ar(0),2,len(ar(0)))&".</Title>"
nm1="pt;"&replace(mid(ar(0),2,len(ar(0))),";"," ")&".;"
txt2 =ar(1)
ar =split(txt2,",")
le=len(ar(0))
l=le-7
lt ="<Lat>"&left(ar(0),l)&"."&right(ar(0),7)&"</Lat>"
nm1=nm1&left(ar(0),l)&"."&right(ar(0),7)&";"
le=len(ar(1))
l=le-7
lg ="<Lng>"&left(ar(1),l)&"."&right(ar(1),7)&"</Lng>"
nm1=nm1&left(ar(1),l)&"."&right(ar(1),7)&";;"
txt2 ="<Point>"&nm&lt&lg&"<Description></Description></Point>"
txt2=replace(txt2,"&"," and ")
nm1=replace(nm1,"&"," and ")
if instr(txt2,",")=0 then
f4.Write(nm1&vbcrlf)
f2.Write(txt2&vbcrlf)
end if
end if
else
n=n+1
end if
else
n=n+1
end if
'end if
next
if n<>0 then
msgbox "Внимание!"&vbcrlf&"ВозможноВы неправильно вписали выражения для замены."&vbcrlf&"Проверьте выражения с кавычками."&vbcrlf&"Исправьте ошибки и запустите конвертор заново."&vbcrlf&"А пока будет потеряно "&n&"точек, не считая потери при репроцессинге."
end if
' Последняя строка выходного файла
f2.Write("</Route>"&vbcrlf)
f1.close()
f2.close()
f4.close()
' добавляем точку в конец названия точки для корректного произношения в LoadStone
path= fso.GetAbsolutePathName("")+"\\"
infile=path+"\\out\\"+"out.txt"
outfile =path+"\\out\\"+"data.txt"
if fso.FileExists(outfile)=True then
fso.DeleteFile outfile, 1
End If
set f1 = fso.OpenTextFile(infile , 1, 0, -2)
set f2 = fso.OpenTextFile(outfile, 8, 1, -2)
s =f1.ReadAll() 'считываем сразу весь входной файл в текстовую переменную
s=replace(s,""",","."",") 'собственно замена, последняя цифра 1 означает - без учета регистра
f2.Write(s) 'записываем результат
f1.close
f2.close
  ' Переместить файл в каталог \tmp
set f2= fso.GetFile(path+"log.txt")
f2.Move path+"\tmp\"
set f2= fso.GetFile(path+"\out\data.txt")
f2.Move path+"\tmp\"
set f2= fso.GetFile(path+"\out\out.txt")
f2.delete
WScript.Quit()
