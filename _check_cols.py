import hdbcli.dbapi
dil = hdbcli.dbapi.connect(address='lo1hdb.dmz.basf-ag.de', port=30015, user='altnict', password='FinJaleymie99:99', encrypt=True, sslValidateCertificate=True, sslCryptoProvider='commoncrypto')
cur = dil.cursor()
cur.execute("SELECT COLUMN_NAME FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME='DIL' AND TABLE_NAME='DMS_DOC_FILES' ORDER BY POSITION")
for r in cur.fetchall():
    print(r[0])
dil.close()
