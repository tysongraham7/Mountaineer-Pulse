import AsyncStorage from '@react-native-async-storage/async-storage';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

const KEY = 'mp_favorite_sports';

type FavoritesContextValue = {
  favorites: string[];
  isFavorite: (sport: string) => boolean;
  toggle: (sport: string) => void;
  ready: boolean;
};

const FavoritesContext = createContext<FavoritesContextValue>({
  favorites: [],
  isFavorite: () => false,
  toggle: () => {},
  ready: false,
});

export function FavoritesProvider({ children }: { children: ReactNode }) {
  const [favorites, setFavorites] = useState<string[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(KEY)
      .then((v) => {
        if (v) setFavorites(JSON.parse(v));
      })
      .finally(() => setReady(true));
  }, []);

  const toggle = (sport: string) => {
    setFavorites((prev) => {
      const next = prev.includes(sport) ? prev.filter((s) => s !== sport) : [...prev, sport];
      AsyncStorage.setItem(KEY, JSON.stringify(next));
      return next;
    });
  };

  return (
    <FavoritesContext.Provider
      value={{ favorites, isFavorite: (s) => favorites.includes(s), toggle, ready }}>
      {children}
    </FavoritesContext.Provider>
  );
}

export const useFavorites = () => useContext(FavoritesContext);
