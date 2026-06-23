@echo off
echo Unregistering VidFetch native messaging host...
reg delete "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.vidfetch.host" /f 2>nul
reg delete "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.vidfetch.host" /f 2>nul
echo Done. (Remove the extension itself from the browser Extensions page.)
echo.
pause
