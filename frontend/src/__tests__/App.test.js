import { render, screen } from '@testing-library/react';
import App from '../App';

test('renders Logstead welcome message', () => {
  render(<App />);
  const linkElement = screen.getByText(/logstead/i);
  expect(linkElement).toBeInTheDocument();
});
