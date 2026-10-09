from abc import ABC, abstractmethod

import pandas as pd


class Collect(ABC):
    
    @abstractmethod
    def collect_data(self) -> pd.DataFrame:
        """Retourne un lot de commandes brutes """
