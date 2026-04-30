(function () {
  const DEFAULTS = {
    additionalCostsUsd: 300,
    loadingUsd: 560,
    freightUsd: 1050,
    usdRate: 4,
    auctionFeeRate: 0.08,
    serviceInsuranceRate: 0.02,
    privateCustomsBaseRate: 0.4,
    fixedExciseBaseUsd: 550,
    customsDutyRate: 0.1,
    deVatRate: 0.21,
    plVatRate: 0.23,
    clearanceDePln: 3000,
    transportPrivatePln: 2500,
    transportCompanyPln: 2100,
    brokerBasicBasePln: 1800,
    brokerBasicRate: 0.02,
    brokerPremiumBasePln: 3600,
    brokerPremiumRate: 0.04,
    employeeBasicShare: 0.4,
    employeePremiumShare: 0.3,
    employeeTopupShare: 0.2,
    employeeFixedPln: 150,
  };

  const locations = Array.isArray(window.TOWING_LOCATIONS) ? window.TOWING_LOCATIONS : [];

  function numberValue(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const value = parseFloat(String(el.value).replace(",", "."));
    return Number.isFinite(value) ? value : fallback;
  }

  function money(value, currency) {
    const safe = Number.isFinite(value) ? value : 0;
    const suffix = currency ? ` ${currency}` : "";
    return `${Math.round(safe).toLocaleString("pl-PL")}${suffix}`;
  }

  function percent(value) {
    const rounded = Math.round(value * 1000) / 10;
    const text = Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1);
    return `${text.replace(".", ",")}%`;
  }

  function stateMedianTowing(state) {
    const values = locations
      .filter((item) => item.state === state)
      .map((item) => item.towingUsd)
      .sort((a, b) => a - b);
    if (!values.length) return 1000;
    return values[Math.floor(values.length / 2)];
  }

  function towingForLocation(state, city) {
    if (!state) return 1000;
    if (city) {
      const normalizedCity = city.trim().toUpperCase();
      const match = locations.find((item) => item.state === state && item.city.trim().toUpperCase() === normalizedCity);
      if (match) return match.towingUsd;
    }
    return stateMedianTowing(state);
  }

  function buildStateOptions() {
    const select = document.getElementById("calcState");
    if (!select) return;
    const states = [...new Set(locations.map((item) => item.state))].sort();
    select.innerHTML = states.map((state) => `<option value="${state}">${state}</option>`).join("");
    select.value = states.includes("FL") ? "FL" : states[0] || "";
    buildLocationOptions();
  }

  function buildLocationOptions() {
    const state = document.getElementById("calcState")?.value;
    const select = document.getElementById("calcLocation");
    if (!select) return;

    const filtered = locations.filter((item) => item.state === state);
    select.innerHTML = [
      `<option value="">Średnia/typowa stawka dla ${state || "stanu"}</option>`,
      ...filtered.map((item, index) => {
        const label = `${item.yard} - ${item.city}, ${item.state} (${money(item.towingUsd, "USD")})`;
        return `<option value="${index}">${label}</option>`;
      }),
    ].join("");
    setTowingFromLocation();
  }

  function setTowingFromLocation() {
    const state = document.getElementById("calcState")?.value;
    const locationSelect = document.getElementById("calcLocation");
    const towingInput = document.getElementById("calcTowing");
    if (!towingInput) return;

    const filtered = locations.filter((item) => item.state === state);
    const selected = locationSelect?.value === "" ? null : filtered[Number(locationSelect?.value)];
    towingInput.value = selected ? selected.towingUsd : stateMedianTowing(state);
  }

  function readInputs(overrides = {}) {
    return {
      bidUsd: overrides.bidUsd ?? numberValue("calcBid", 15000),
      additionalCostsUsd: overrides.additionalCostsUsd ?? numberValue("calcAdditional", DEFAULTS.additionalCostsUsd),
      towingUsd: overrides.towingUsd ?? numberValue("calcTowing", stateMedianTowing(document.getElementById("calcState")?.value || "FL")),
      loadingUsd: overrides.loadingUsd ?? numberValue("calcLoading", DEFAULTS.loadingUsd),
      freightUsd: overrides.freightUsd ?? numberValue("calcFreight", DEFAULTS.freightUsd),
      usdRate: overrides.usdRate ?? numberValue("calcUsdRate", DEFAULTS.usdRate),
      exciseRate: overrides.exciseRate ?? numberValue("calcExcise", 0.031),
      topupPln: overrides.topupPln ?? numberValue("calcTopup", 0),
    };
  }

  function calculateImportCosts(input) {
    const auctionFeeUsd = input.bidUsd * DEFAULTS.auctionFeeRate;
    const usaTotalUsd = input.additionalCostsUsd + input.bidUsd + auctionFeeUsd + input.towingUsd + input.loadingUsd + input.freightUsd;
    const usaTotalPln = usaTotalUsd * input.usdRate;

    const serviceInsuranceUsd = usaTotalUsd * DEFAULTS.serviceInsuranceRate;
    const claimServiceUsd = serviceInsuranceUsd / 2;

    const privateCustomsBasePln = (usaTotalPln * DEFAULTS.privateCustomsBaseRate) + (DEFAULTS.fixedExciseBaseUsd * input.usdRate);
    const privateDutyPln = privateCustomsBasePln * DEFAULTS.customsDutyRate;
    const privateVatDePln = (privateCustomsBasePln + privateDutyPln) * DEFAULTS.deVatRate;
    const privateDeFeesPln = DEFAULTS.clearanceDePln + privateDutyPln + privateVatDePln + DEFAULTS.transportPrivatePln;
    const privateBeforeExcisePln = usaTotalPln + privateDeFeesPln;
    const privateExcisePln = (privateBeforeExcisePln * 0.5) * input.exciseRate;
    const privateTotalPln = privateBeforeExcisePln + privateExcisePln;

    const companyDutyPln = usaTotalPln * DEFAULTS.customsDutyRate;
    const companyDeFeesPln = DEFAULTS.clearanceDePln + companyDutyPln;
    const companyExcisePln = ((input.bidUsd + DEFAULTS.fixedExciseBaseUsd) * input.usdRate) * input.exciseRate;
    const companyNetPln = usaTotalPln + companyDeFeesPln + companyExcisePln;
    const companyGrossPln = (companyNetPln * (1 + DEFAULTS.plVatRate)) + DEFAULTS.transportCompanyPln;

    const brokerBasicNetPln = (input.bidUsd * DEFAULTS.brokerBasicRate * input.usdRate) + DEFAULTS.brokerBasicBasePln;
    const brokerPremiumNetPln = (input.bidUsd * DEFAULTS.brokerPremiumRate * input.usdRate) + DEFAULTS.brokerPremiumBasePln;
    const brokerBasicGrossPln = brokerBasicNetPln * (1 + DEFAULTS.plVatRate);
    const brokerPremiumGrossPln = brokerPremiumNetPln * (1 + DEFAULTS.plVatRate);
    const employeeBasicPln = (brokerBasicNetPln * DEFAULTS.employeeBasicShare) + (input.topupPln * DEFAULTS.employeeTopupShare) + DEFAULTS.employeeFixedPln;
    const employeePremiumPln = (brokerPremiumNetPln * DEFAULTS.employeePremiumShare) + (input.topupPln * DEFAULTS.employeeTopupShare);

    return {
      input,
      auctionFeeUsd,
      usaTotalUsd,
      usaTotalPln,
      serviceInsuranceUsd,
      claimServiceUsd,
      serviceInsuranceTotalUsd: serviceInsuranceUsd + claimServiceUsd,
      privateCustomsBasePln,
      privateDutyPln,
      privateVatDePln,
      privateDeFeesPln,
      privateBeforeExcisePln,
      privateExcisePln,
      privateTotalPln,
      companyDutyPln,
      companyDeFeesPln,
      companyExcisePln,
      companyNetPln,
      companyGrossPln,
      brokerBasicNetPln,
      brokerBasicGrossPln,
      brokerPremiumNetPln,
      brokerPremiumGrossPln,
      employeeBasicPln,
      employeePremiumPln,
    };
  }

  function renderResults(result) {
    const target = document.getElementById("calcResults");
    if (!target) return;

    target.innerHTML = `
      <div class="calc-kpis">
        <div><strong>${money(result.usaTotalUsd, "USD")}</strong><span>Suma USA</span></div>
        <div><strong>${money(result.privateTotalPln, "PLN")}</strong><span>Os. prywatna z akcyzą ${percent(result.input.exciseRate)}</span></div>
        <div><strong>${money(result.companyGrossPln, "PLN")}</strong><span>Firma brutto z akcyzą ${percent(result.input.exciseRate)}</span></div>
      </div>
      <div class="calc-grid">
        <div class="calc-panel">
          <h3>Koszty USA</h3>
          ${row("Kwota licytacji", money(result.input.bidUsd, "USD"))}
          ${row("Prowizja aukcyjna 8%", money(result.auctionFeeUsd, "USD"))}
          ${row("Towing", money(result.input.towingUsd, "USD"))}
          ${row("Koszty dodatkowe", money(result.input.additionalCostsUsd, "USD"))}
          ${row("Załadunki", money(result.input.loadingUsd, "USD"))}
          ${row("Fracht", money(result.input.freightUsd, "USD"))}
          ${row("Suma", money(result.usaTotalUsd, "USD"), true)}
          ${row("Serwis + ubezpieczenie 2% + 1%", money(result.serviceInsuranceTotalUsd, "USD"))}
        </div>
        <div class="calc-panel">
          <h3>Osoba prywatna</h3>
          ${row("Baza odprawy DE", money(result.privateCustomsBasePln, "PLN"))}
          ${row("Cło 10%", money(result.privateDutyPln, "PLN"))}
          ${row("VAT DE 21%", money(result.privateVatDePln, "PLN"))}
          ${row("Opłaty DE + transport PL", money(result.privateDeFeesPln, "PLN"))}
          ${row("Wartość przed akcyzą", money(result.privateBeforeExcisePln, "PLN"))}
          ${row(`Akcyza ${percent(result.input.exciseRate)}`, money(result.privateExcisePln, "PLN"))}
          ${row("Razem", money(result.privateTotalPln, "PLN"), true)}
        </div>
        <div class="calc-panel">
          <h3>Firma</h3>
          ${row("Cło 10%", money(result.companyDutyPln, "PLN"))}
          ${row("Opłaty DE", money(result.companyDeFeesPln, "PLN"))}
          ${row(`Akcyza ${percent(result.input.exciseRate)}`, money(result.companyExcisePln, "PLN"))}
          ${row("Netto", money(result.companyNetPln, "PLN"))}
          ${row("Brutto + transport PL", money(result.companyGrossPln, "PLN"), true)}
        </div>
        <div class="calc-panel">
          <h3>Prowizje</h3>
          ${row("Prowizja 1800 + 2% netto", money(result.brokerBasicNetPln, "PLN"))}
          ${row("Prowizja 1800 + 2% brutto", money(result.brokerBasicGrossPln, "PLN"))}
          ${row("Prowizja 3600 + 4% netto", money(result.brokerPremiumNetPln, "PLN"))}
          ${row("Prowizja 3600 + 4% brutto", money(result.brokerPremiumGrossPln, "PLN"))}
          ${row("Pracownik - wariant 1", money(result.employeeBasicPln, "PLN"))}
          ${row("Pracownik - wariant 2", money(result.employeePremiumPln, "PLN"))}
        </div>
      </div>
    `;
  }

  function row(label, value, strong) {
    return `<div class="calc-row ${strong ? "strong" : ""}"><span>${label}</span><strong>${value}</strong></div>`;
  }

  function calculateAndRenderImportCosts() {
    const result = calculateImportCosts(readInputs());
    renderResults(result);
    return result;
  }

  function selectLocationForLot(lot) {
    const stateSelect = document.getElementById("calcState");
    const locationSelect = document.getElementById("calcLocation");
    const state = lot.location_state || "FL";
    if (stateSelect && [...stateSelect.options].some((option) => option.value === state)) {
      stateSelect.value = state;
      buildLocationOptions();
    }

    if (!locationSelect || !lot.location_city) return;
    const city = lot.location_city.trim().toUpperCase();
    const options = [...locationSelect.options];
    const match = options.find((option) => option.textContent.toUpperCase().includes(city));
    if (match) {
      locationSelect.value = match.value;
      setTowingFromLocation();
    }
  }

  function fillCalculatorFromLot(lotId) {
    if (!window.searchData) return;
    const lots = [...window.searchData.top_recommendations, ...window.searchData.all_results];
    const item = lots.find((entry) => entry.lot.lot_id === lotId);
    if (!item) return;
    const lot = item.lot;
    document.getElementById("calcBid").value = lot.current_bid_usd || 0;
    selectLocationForLot(lot);
    calculateAndRenderImportCosts();
    document.getElementById("calculatorCard")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function estimateLotTotalPln(lot) {
    if (!lot || !lot.current_bid_usd) return null;
    const state = lot.location_state || "FL";
    const towingUsd = towingForLocation(state, lot.location_city);
    const result = calculateImportCosts(readInputs({
      bidUsd: Number(lot.current_bid_usd),
      towingUsd,
      exciseRate: 0.031,
    }));
    return {
      privateTotalPln: result.privateTotalPln,
      companyGrossPln: result.companyGrossPln,
      towingUsd,
    };
  }

  function resetCalculatorDefaults() {
    document.getElementById("calcBid").value = 15000;
    document.getElementById("calcAdditional").value = DEFAULTS.additionalCostsUsd;
    document.getElementById("calcLoading").value = DEFAULTS.loadingUsd;
    document.getElementById("calcFreight").value = DEFAULTS.freightUsd;
    document.getElementById("calcUsdRate").value = DEFAULTS.usdRate;
    document.getElementById("calcExcise").value = 0.031;
    document.getElementById("calcTopup").value = 0;
    buildStateOptions();
    calculateAndRenderImportCosts();
  }

  function initCalculator() {
    buildStateOptions();
    ["calcBid", "calcAdditional", "calcTowing", "calcLoading", "calcFreight", "calcUsdRate", "calcExcise", "calcTopup"].forEach((id) => {
      document.getElementById(id)?.addEventListener("input", calculateAndRenderImportCosts);
      document.getElementById(id)?.addEventListener("change", calculateAndRenderImportCosts);
    });
    document.getElementById("calcState")?.addEventListener("change", () => {
      buildLocationOptions();
      calculateAndRenderImportCosts();
    });
    document.getElementById("calcLocation")?.addEventListener("change", () => {
      setTowingFromLocation();
      calculateAndRenderImportCosts();
    });
    calculateAndRenderImportCosts();
  }

  window.calculateImportCosts = calculateImportCosts;
  window.calculateAndRenderImportCosts = calculateAndRenderImportCosts;
  window.fillCalculatorFromLot = fillCalculatorFromLot;
  window.estimateLotTotalPln = estimateLotTotalPln;
  window.resetCalculatorDefaults = resetCalculatorDefaults;

  document.addEventListener("DOMContentLoaded", initCalculator);
})();
