
import { render, screen } from '@testing-library/react';
import App from '../App';

test('renders Logstead welcome message', () => {
  render(<App />);
  const elements = screen.getAllByText(/logstead/i);
  expect(elements.length).toBeGreaterThan(0);
});
