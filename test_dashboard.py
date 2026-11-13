from app import app

app.config['TESTING'] = True
client = app.test_client()

# Test login with strong password
response = client.post('/login', data={'username': 'admin', 'password': 'Str0ng!Passw0rd#2026'})
print('Login status:', response.status_code)

if response.status_code == 302:
    # Test dashboard access
    dashboard = client.get('/')
    print('Dashboard status:', dashboard.status_code)
    print('Dashboard length:', len(dashboard.data))
    print('Dashboard contains devices:', b'Daftar Perangkat' in dashboard.data or b'Devices' in dashboard.data)
    print('Dashboard contains stats:', b'Statistik' in dashboard.data or b'Stats' in dashboard.data)
else:
    print('Login failed. Response content length:', len(response.data))
    print('First 200 chars:', response.data[:200])
