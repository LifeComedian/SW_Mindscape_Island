"use client";
import {createContext,useContext,type ReactNode} from "react";
const Night=createContext(false);
export function HolidayNight({night,children}:{night:boolean;children:ReactNode}){return <Night.Provider value={night}>{children}</Night.Provider>;}
export function useHolidayNight(){return useContext(Night);}
