
import { useEffect, useState } from 'react';

function App() {
  const [greeting, setGreeting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
  fetch('/api/hello')
      .then((res) => {
        if (!res.ok) throw new Error('API error');
        return res.json();
      })
      .then((data) => setGreeting(data.greeting))
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div style={{ maxWidth: 600, margin: '2rem auto', textAlign: 'center' }}>
      <h1>Logstead Property & Equipment Tracker</h1>
      <p>Welcome to Logstead! Your dashboard will appear here.</p>
      <div style={{ marginTop: '2rem' }}>
        <strong>API Test:</strong>
        {greeting && <div style={{ marginTop: 8 }}>{greeting}</div>}
        {error && <div style={{ marginTop: 8, color: 'red' }}>{error}</div>}
      </div>
    </div>
  );
}

export default App
