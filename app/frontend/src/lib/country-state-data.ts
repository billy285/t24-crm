export interface CountryOption {
  code: string;
  label: string;
  labelCn: string;
}

export interface StateOption {
  code: string;
  label: string;
}

export interface CityOption {
  label: string;
}

export const countries: CountryOption[] = [
  { code: 'US', label: 'United States', labelCn: '美国' },
  { code: 'CA', label: 'Canada', labelCn: '加拿大' },
  { code: 'GB', label: 'United Kingdom', labelCn: '英国' },
  { code: 'AU', label: 'Australia', labelCn: '澳大利亚' },
];

export const statesByCountry: Record<string, StateOption[]> = {
  US: [
    { code: 'AL', label: 'Alabama' }, { code: 'AK', label: 'Alaska' }, { code: 'AZ', label: 'Arizona' },
    { code: 'AR', label: 'Arkansas' }, { code: 'CA', label: 'California' }, { code: 'CO', label: 'Colorado' },
    { code: 'CT', label: 'Connecticut' }, { code: 'DE', label: 'Delaware' }, { code: 'FL', label: 'Florida' },
    { code: 'GA', label: 'Georgia' }, { code: 'HI', label: 'Hawaii' }, { code: 'ID', label: 'Idaho' },
    { code: 'IL', label: 'Illinois' }, { code: 'IN', label: 'Indiana' }, { code: 'IA', label: 'Iowa' },
    { code: 'KS', label: 'Kansas' }, { code: 'KY', label: 'Kentucky' }, { code: 'LA', label: 'Louisiana' },
    { code: 'ME', label: 'Maine' }, { code: 'MD', label: 'Maryland' }, { code: 'MA', label: 'Massachusetts' },
    { code: 'MI', label: 'Michigan' }, { code: 'MN', label: 'Minnesota' }, { code: 'MS', label: 'Mississippi' },
    { code: 'MO', label: 'Missouri' }, { code: 'MT', label: 'Montana' }, { code: 'NE', label: 'Nebraska' },
    { code: 'NV', label: 'Nevada' }, { code: 'NH', label: 'New Hampshire' }, { code: 'NJ', label: 'New Jersey' },
    { code: 'NM', label: 'New Mexico' }, { code: 'NY', label: 'New York' }, { code: 'NC', label: 'North Carolina' },
    { code: 'ND', label: 'North Dakota' }, { code: 'OH', label: 'Ohio' }, { code: 'OK', label: 'Oklahoma' },
    { code: 'OR', label: 'Oregon' }, { code: 'PA', label: 'Pennsylvania' }, { code: 'RI', label: 'Rhode Island' },
    { code: 'SC', label: 'South Carolina' }, { code: 'SD', label: 'South Dakota' }, { code: 'TN', label: 'Tennessee' },
    { code: 'TX', label: 'Texas' }, { code: 'UT', label: 'Utah' }, { code: 'VT', label: 'Vermont' },
    { code: 'VA', label: 'Virginia' }, { code: 'WA', label: 'Washington' }, { code: 'WV', label: 'West Virginia' },
    { code: 'WI', label: 'Wisconsin' }, { code: 'WY', label: 'Wyoming' }, { code: 'DC', label: 'Washington D.C.' },
  ],
  CA: [
    { code: 'AB', label: 'Alberta' }, { code: 'BC', label: 'British Columbia' },
    { code: 'MB', label: 'Manitoba' }, { code: 'NB', label: 'New Brunswick' },
    { code: 'NL', label: 'Newfoundland and Labrador' }, { code: 'NS', label: 'Nova Scotia' },
    { code: 'NT', label: 'Northwest Territories' }, { code: 'NU', label: 'Nunavut' },
    { code: 'ON', label: 'Ontario' }, { code: 'PE', label: 'Prince Edward Island' },
    { code: 'QC', label: 'Quebec' }, { code: 'SK', label: 'Saskatchewan' }, { code: 'YT', label: 'Yukon' },
  ],
  GB: [
    { code: 'ENG', label: 'England' }, { code: 'SCT', label: 'Scotland' },
    { code: 'WLS', label: 'Wales' }, { code: 'NIR', label: 'Northern Ireland' },
    { code: 'LDN', label: 'London' }, { code: 'BRM', label: 'Birmingham' },
    { code: 'MAN', label: 'Manchester' }, { code: 'LDS', label: 'Leeds' },
    { code: 'LIV', label: 'Liverpool' }, { code: 'BRS', label: 'Bristol' },
    { code: 'SHF', label: 'Sheffield' }, { code: 'EDH', label: 'Edinburgh' },
    { code: 'GLA', label: 'Glasgow' }, { code: 'CRD', label: 'Cardiff' },
    { code: 'BEL', label: 'Belfast' },
  ],
  AU: [
    { code: 'NSW', label: 'New South Wales' }, { code: 'VIC', label: 'Victoria' },
    { code: 'QLD', label: 'Queensland' }, { code: 'WA', label: 'Western Australia' },
    { code: 'SA', label: 'South Australia' }, { code: 'TAS', label: 'Tasmania' },
    { code: 'ACT', label: 'Australian Capital Territory' }, { code: 'NT', label: 'Northern Territory' },
  ],
};

// Cities by country-state key
export const citiesByState: Record<string, CityOption[]> = {
  // US States - major cities
  'US-CA': [
    { label: 'Los Angeles' }, { label: 'San Francisco' }, { label: 'San Diego' }, { label: 'San Jose' },
    { label: 'Sacramento' }, { label: 'Fresno' }, { label: 'Oakland' }, { label: 'Irvine' },
    { label: 'Anaheim' }, { label: 'Long Beach' }, { label: 'Pasadena' }, { label: 'Alhambra' },
    { label: 'Arcadia' }, { label: 'Monterey Park' }, { label: 'Rowland Heights' }, { label: 'Walnut' },
    { label: 'Diamond Bar' }, { label: 'Temple City' }, { label: 'El Monte' }, { label: 'Rosemead' },
    { label: 'Cupertino' }, { label: 'Milpitas' }, { label: 'Fremont' }, { label: 'Santa Clara' },
  ],
  'US-NY': [
    { label: 'New York City' }, { label: 'Brooklyn' }, { label: 'Queens' }, { label: 'Manhattan' },
    { label: 'Flushing' }, { label: 'Buffalo' }, { label: 'Rochester' }, { label: 'Albany' },
    { label: 'Syracuse' }, { label: 'Chinatown' },
  ],
  'US-TX': [
    { label: 'Houston' }, { label: 'Dallas' }, { label: 'Austin' }, { label: 'San Antonio' },
    { label: 'Fort Worth' }, { label: 'El Paso' }, { label: 'Plano' }, { label: 'Sugar Land' },
  ],
  'US-FL': [
    { label: 'Miami' }, { label: 'Orlando' }, { label: 'Tampa' }, { label: 'Jacksonville' },
    { label: 'Fort Lauderdale' }, { label: 'St. Petersburg' },
  ],
  'US-IL': [
    { label: 'Chicago' }, { label: 'Aurora' }, { label: 'Naperville' }, { label: 'Schaumburg' },
  ],
  'US-WA': [
    { label: 'Seattle' }, { label: 'Tacoma' }, { label: 'Bellevue' }, { label: 'Redmond' },
    { label: 'Kirkland' }, { label: 'Kent' },
  ],
  'US-MA': [
    { label: 'Boston' }, { label: 'Cambridge' }, { label: 'Worcester' }, { label: 'Quincy' },
  ],
  'US-NJ': [
    { label: 'Newark' }, { label: 'Jersey City' }, { label: 'Edison' }, { label: 'Fort Lee' },
    { label: 'Palisades Park' },
  ],
  'US-PA': [
    { label: 'Philadelphia' }, { label: 'Pittsburgh' }, { label: 'Allentown' },
  ],
  'US-GA': [
    { label: 'Atlanta' }, { label: 'Savannah' }, { label: 'Augusta' }, { label: 'Duluth' },
  ],
  'US-VA': [
    { label: 'Virginia Beach' }, { label: 'Richmond' }, { label: 'Arlington' }, { label: 'Fairfax' },
  ],
  'US-NV': [
    { label: 'Las Vegas' }, { label: 'Henderson' }, { label: 'Reno' },
  ],
  'US-OH': [
    { label: 'Columbus' }, { label: 'Cleveland' }, { label: 'Cincinnati' },
  ],
  'US-AZ': [
    { label: 'Phoenix' }, { label: 'Tucson' }, { label: 'Mesa' }, { label: 'Scottsdale' },
  ],
  'US-CO': [
    { label: 'Denver' }, { label: 'Colorado Springs' }, { label: 'Aurora' }, { label: 'Boulder' },
  ],
  'US-MD': [
    { label: 'Baltimore' }, { label: 'Rockville' }, { label: 'Bethesda' },
  ],
  'US-OR': [
    { label: 'Portland' }, { label: 'Salem' }, { label: 'Eugene' },
  ],
  'US-MI': [
    { label: 'Detroit' }, { label: 'Grand Rapids' }, { label: 'Ann Arbor' },
  ],
  'US-NC': [
    { label: 'Charlotte' }, { label: 'Raleigh' }, { label: 'Durham' },
  ],
  'US-MN': [
    { label: 'Minneapolis' }, { label: 'Saint Paul' },
  ],
  'US-HI': [
    { label: 'Honolulu' }, { label: 'Hilo' },
  ],
  'US-AL': [
    { label: 'Birmingham' }, { label: 'Montgomery' }, { label: 'Huntsville' }, { label: 'Mobile' },
    { label: 'Tuscaloosa' },
  ],
  'US-AK': [
    { label: 'Anchorage' }, { label: 'Fairbanks' }, { label: 'Juneau' }, { label: 'Wasilla' },
  ],
  'US-AR': [
    { label: 'Little Rock' }, { label: 'Fayetteville' }, { label: 'Fort Smith' }, { label: 'Springdale' },
    { label: 'Jonesboro' },
  ],
  'US-CT': [
    { label: 'Bridgeport' }, { label: 'New Haven' }, { label: 'Stamford' }, { label: 'Hartford' },
    { label: 'Waterbury' },
  ],
  'US-DE': [
    { label: 'Wilmington' }, { label: 'Dover' }, { label: 'Newark' }, { label: 'Middletown' },
  ],
  'US-DC': [
    { label: 'Washington' },
  ],
  'US-ID': [
    { label: 'Boise' }, { label: 'Meridian' }, { label: 'Nampa' }, { label: 'Idaho Falls' },
    { label: 'Pocatello' },
  ],
  'US-IN': [
    { label: 'Indianapolis' }, { label: 'Fort Wayne' }, { label: 'Evansville' }, { label: 'South Bend' },
    { label: 'Carmel' },
  ],
  'US-IA': [
    { label: 'Des Moines' }, { label: 'Cedar Rapids' }, { label: 'Davenport' }, { label: 'Sioux City' },
    { label: 'Iowa City' },
  ],
  'US-KS': [
    { label: 'Wichita' }, { label: 'Overland Park' }, { label: 'Kansas City' }, { label: 'Topeka' },
    { label: 'Olathe' },
  ],
  'US-KY': [
    { label: 'Louisville' }, { label: 'Lexington' }, { label: 'Bowling Green' }, { label: 'Owensboro' },
    { label: 'Covington' },
  ],
  'US-LA': [
    { label: 'New Orleans' }, { label: 'Baton Rouge' }, { label: 'Shreveport' }, { label: 'Lafayette' },
    { label: 'Lake Charles' },
  ],
  'US-ME': [
    { label: 'Portland' }, { label: 'Lewiston' }, { label: 'Bangor' }, { label: 'South Portland' },
    { label: 'Augusta' },
  ],
  'US-MS': [
    { label: 'Jackson' }, { label: 'Gulfport' }, { label: 'Southaven' }, { label: 'Biloxi' },
    { label: 'Hattiesburg' },
  ],
  'US-MO': [
    { label: 'Kansas City' }, { label: 'St. Louis' }, { label: 'Springfield' }, { label: 'Columbia' },
    { label: 'Independence' },
  ],
  'US-MT': [
    { label: 'Billings' }, { label: 'Missoula' }, { label: 'Great Falls' }, { label: 'Bozeman' },
    { label: 'Helena' },
  ],
  'US-NE': [
    { label: 'Omaha' }, { label: 'Lincoln' }, { label: 'Bellevue' }, { label: 'Grand Island' },
    { label: 'Kearney' },
  ],
  'US-NH': [
    { label: 'Manchester' }, { label: 'Nashua' }, { label: 'Concord' }, { label: 'Derry' },
    { label: 'Portsmouth' },
  ],
  'US-NM': [
    { label: 'Albuquerque' }, { label: 'Santa Fe' }, { label: 'Las Cruces' }, { label: 'Rio Rancho' },
    { label: 'Roswell' },
  ],
  'US-ND': [
    { label: 'Fargo' }, { label: 'Bismarck' }, { label: 'Grand Forks' }, { label: 'Minot' },
    { label: 'West Fargo' },
  ],
  'US-OK': [
    { label: 'Oklahoma City' }, { label: 'Tulsa' }, { label: 'Norman' }, { label: 'Broken Arrow' },
    { label: 'Edmond' },
  ],
  'US-RI': [
    { label: 'Providence' }, { label: 'Warwick' }, { label: 'Cranston' }, { label: 'Pawtucket' },
    { label: 'Newport' },
  ],
  'US-SC': [
    { label: 'Charleston' }, { label: 'Columbia' }, { label: 'Greenville' }, { label: 'Myrtle Beach' },
    { label: 'Rock Hill' },
  ],
  'US-SD': [
    { label: 'Sioux Falls' }, { label: 'Rapid City' }, { label: 'Aberdeen' }, { label: 'Brookings' },
    { label: 'Watertown' },
  ],
  'US-TN': [
    { label: 'Nashville' }, { label: 'Memphis' }, { label: 'Knoxville' }, { label: 'Chattanooga' },
    { label: 'Franklin' },
  ],
  'US-UT': [
    { label: 'Salt Lake City' }, { label: 'West Valley City' }, { label: 'Provo' }, { label: 'Ogden' },
    { label: 'St. George' },
  ],
  'US-VT': [
    { label: 'Burlington' }, { label: 'South Burlington' }, { label: 'Rutland' }, { label: 'Montpelier' },
    { label: 'Bennington' },
  ],
  'US-WV': [
    { label: 'Charleston' }, { label: 'Huntington' }, { label: 'Morgantown' }, { label: 'Parkersburg' },
    { label: 'Wheeling' },
  ],
  'US-WI': [
    { label: 'Milwaukee' }, { label: 'Madison' }, { label: 'Green Bay' }, { label: 'Kenosha' },
    { label: 'Racine' },
  ],
  'US-WY': [
    { label: 'Cheyenne' }, { label: 'Casper' }, { label: 'Laramie' }, { label: 'Gillette' },
    { label: 'Rock Springs' },
  ],
  // Canada
  'CA-BC': [
    { label: 'Vancouver' }, { label: 'Victoria' }, { label: 'Richmond' }, { label: 'Burnaby' },
    { label: 'Surrey' },
  ],
  'CA-ON': [
    { label: 'Toronto' }, { label: 'Ottawa' }, { label: 'Mississauga' }, { label: 'Markham' },
    { label: 'Richmond Hill' },
  ],
  'CA-QC': [
    { label: 'Montreal' }, { label: 'Quebec City' }, { label: 'Laval' },
  ],
  'CA-AB': [
    { label: 'Calgary' }, { label: 'Edmonton' },
  ],
  // UK
  'GB-ENG': [
    { label: 'London' }, { label: 'Birmingham' }, { label: 'Manchester' }, { label: 'Liverpool' },
    { label: 'Leeds' }, { label: 'Bristol' }, { label: 'Sheffield' },
  ],
  'GB-SCT': [
    { label: 'Edinburgh' }, { label: 'Glasgow' }, { label: 'Aberdeen' },
  ],
  'GB-WLS': [
    { label: 'Cardiff' }, { label: 'Swansea' },
  ],
  // Australia
  'AU-NSW': [
    { label: 'Sydney' }, { label: 'Newcastle' }, { label: 'Wollongong' },
  ],
  'AU-VIC': [
    { label: 'Melbourne' }, { label: 'Geelong' },
  ],
  'AU-QLD': [
    { label: 'Brisbane' }, { label: 'Gold Coast' }, { label: 'Cairns' },
  ],
};

export function getStatesForCountry(countryCode: string): StateOption[] {
  return statesByCountry[countryCode] || [];
}

export function getCitiesForState(countryCode: string, stateCode: string): CityOption[] {
  return citiesByState[`${countryCode}-${stateCode}`] || [];
}

export function getCountryLabel(code: string): string {
  const c = countries.find(c => c.code === code);
  return c ? `${c.labelCn} (${c.label})` : code;
}

export function getStateLabel(countryCode: string, stateCode: string): string {
  const states = statesByCountry[countryCode] || [];
  const s = states.find(s => s.code === stateCode);
  return s ? s.label : stateCode;
}
