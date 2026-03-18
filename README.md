# cyberduck-automation

#update the path if required 
curl -sL "https://profiles.cyberduck.io/S3%20(Credentials%20from%20AWS%20Command%20Line%20Interface).cyberduckprofile" -o "/mnt/c/Users/nizar/AppData/Roaming/Cyberduck/Profiles/S3 (Credentials from AWS Command Line Interface).cyberduckprofile" && echo "Downloaded OK"


When creating a bookmark 
- select the profile from the dropdown 
- In the Username field (labeled "Profile Name in ~/.aws/credentials"), enter
: cyberduck-sso
- Then run ./cyberduck-sso.bash to populate the credentials

That profile reads aws_access_key_id, aws_secret_access_key, and 
aws_session_token directly from C:\Users\nizar\.aws\credentials — no 
password prompt.