import { ITEMIZED_PAGES } from "../lib/itemizedPages";
import ItemizedExpensesPage from "./ItemizedExpensesPage";

/** Repairs tab (Schedule E line 14). */
export default function RepairsPage() {
  return <ItemizedExpensesPage definition={ITEMIZED_PAGES.repairs} />;
}
