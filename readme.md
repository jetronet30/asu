#-------- windows --------
py -m venv .venv    
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.venv\Scripts\activate
python.exe -m pip install --upgrade pip

pip install -r requirements.txt

python -m asu

pyinstaller --onefile --windowed --add-data "models/trocr-large-printed;models/trocr-large-printed" --add-data "best.pt;." -n "ASU" asu\__main__.py

pyinstaller --onefile --add-data "models/trocr-large-printed;models/trocr-large-printed" --add-data "best.pt;." -n "ASU" asu\__main__.py

#-------- linux  ubuntu--------
python3 -m venv .venv     
source .venv/bin/activate   
pip install --upgrade pip
pip install -r requirements_u.txt

python -m asu

pyinstaller --onefile --add-data "models/trocr-large-printed:models/trocr-large-printed" --add-data "best.pt:." -n ASU asu/__main__.py




