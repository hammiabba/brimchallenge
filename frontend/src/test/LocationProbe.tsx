import { useLocation } from 'react-router'

/** Writes the current router location into a hidden element, so tests can read what a screen put in the URL. */
export function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location" hidden>{`${location.pathname}${location.search}`}</output>
}
