import { defineMcp } from "@lovable.dev/mcp-js";
import calculateImportCostTool from "./tools/calculate-import-cost";

// PUBLICZNY serwer MCP — bez uwierzytelnienia.
// Zawiera wyłącznie narzędzia neutralne (czysta kalkulacja), bez dostępu do bazy,
// watchlisty, klientów, scrapera ani raportów. Każdy w internecie może je wywołać.
export default defineMcp({
  name: "car-auction-buddy-mcp",
  title: "Car Auction Buddy — narzędzia publiczne",
  version: "0.1.0",
  instructions:
    "Publiczny zestaw narzędzi Car Auction Buddy. Zawiera wyłącznie deterministyczny kalkulator kosztu importu auta z USA do Polski. Nie ma dostępu do prywatnych danych aplikacji (aukcje, watchlist, klienci, raporty).",
  tools: [calculateImportCostTool],
});
