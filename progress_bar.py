from ETA import ETA
from seconds_to_time import seconds_to_time


class progress_bar:
    """
    progress is float [0, 1]
    length is character count length of progress bar (not including start and end strings)
    no newline is printed after the progress bar
    """
    def __init__(self, length: int, start_string = "~<{", end_string = "}>~", fill_char = "/", empty_char = "-", with_percentage = True, with_ETA = True, with_rate = True, rate_units = ""):
        assert (type(length) == int), "type of length was not int"
        assert (length > 0), "length was negative"
        assert (type(start_string) == str), "start_string was not string"
        assert (type(end_string) == str), "end_string was not string"
        assert (type(fill_char) == str), "fill_char was not string"
        assert (len(fill_char) == 1), "len(fill_char) was not 1"
        assert (type(empty_char) == str), "empty_char was not string"
        assert (len(empty_char) == 1), "len(empty_char) was not 1"
        if with_rate:
            assert(type(rate_units) == str), "rate units was not a string"

        self.__length = length
        self.__start_string = start_string
        self.__end_string = end_string
        self.__fill_char = fill_char
        self.__empty_char = empty_char
        self.__with_percentage = with_percentage
        self.__with_ETA = with_ETA
        self.__with_rate = with_rate
        self.__rate_units = rate_units
        self.__ETA = None # don't start the ETA stopwatch until first update

        self.__output_string = "" # not defined yet

        return None


    def __update_output_string(self, progress: float, rate_progress: float = None) -> None:
        assert (type(progress) == float), "type of progress was not float"
        assert (progress <= 1), "progress was greater than 1"
        assert (type(rate_progress) in [float, int] or rate_progress is None), "rate_progress was not None or float/int"

        output_string = self.__start_string
        progress_character_count = int(progress*self.__length)
        output_string += progress_character_count * self.__fill_char
        output_string += (self.__length - progress_character_count) * self.__empty_char
        output_string += self.__end_string
        if self.__with_percentage:
            output_string += " {:6.2f}%".format(progress*100)
        if self.__with_ETA:
            if self.__ETA is None:
                self.__ETA = ETA() # start ETA stopwatch on first update
            output_string += " | {} remaining".format(seconds_to_time(self.__ETA.get_time_remaining(progress)))
        if self.__with_rate and rate_progress is not None:
            try:
                output_string += " | {:8.2f} {}/s".format(rate_progress/self.__ETA.get_time_since_init(), self.__rate_units)
            except ZeroDivisionError:
                output_string += " | {} {}/s".format("N/A", self.__rate_units)

        self.__output_string = output_string
        return None
    
    def print_progress_bar(self, progress: float, rate_progress: float = None) -> None:
        """
        progress is [0, 1],
        rate_progress and rate units are only used if this object was initialized with with_rate = True,
        example of rate progress and rate units:
        rate_progress = 80.4 (total MB processed)
        rate_units = "MB" (units of MB, athis method will divide by seconds, don't worry)
        """
        self.__update_output_string(progress, rate_progress)
        print("\r" + self.__output_string, end="")

