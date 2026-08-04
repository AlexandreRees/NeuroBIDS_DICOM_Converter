classdef CheckerFlickerSine < handle
   properties
       tex
       stimParams
       flickerFrequency {mustBeNumeric}
       lastSwitchTime   {mustBeNumeric}
       show  {mustBeNumeric}
       phaseDirection {mustBeNumeric}
       lasttaghir {mustBeNumeric}
   end
   methods (Access = public)
      function obj = CheckerFlickerSine(checkerStimParams,flickerFrequency)
        if nargin>=1  && isfield(checkerStimParams,'mean') ...
                     && isfield(checkerStimParams,'amplitude') ...
                     && isfield(checkerStimParams,'spatialF') ...
                     && isfield(checkerStimParams,'gratingColor') ...
                     && isfield(checkerStimParams,'cyclesPerRotation')
            % Passed in stim params
            obj.stimParams = checkerStimParams;          
        end
        	
		if nargin==2
            % Passed in pulse time 
			obj.flickerFrequency = flickerFrequency;
		end 
	  end

      function obj = createTextures(obj, diameter,screenProperties)

        cyclePerPixel = obj.stimParams.spatialF*screenProperties.degPerPix; %spatialF in cyclesPerDeg
		radius = diameter/2;
		[X,Y] = meshgrid(-radius(1):1:radius(1),-radius(2):1:radius(2));
        R = sqrt(X.^2+Y.^2);
        T = atan2(-Y,X);

        % Color code of the stimulus define RGB here
        % grating colors
        colorBlackAndWhite = 0;
        colorBlueAndYellow = 1;
        colorRedAndGreen   = 2;

        % Calculation for deg/second -> frames/cycle
        % deg/second * cycles/deg * seconds/frame = cycles/frame
        % 1/cycles/frame = frames/cycle

        % read the isoluminant R and G values
        Redlevel = load('RedLevel.mat');
        Redlevel= (Redlevel.RedLevel);
        Greenlevel = load('GreenLevel.mat');
        Greenlevel = (Greenlevel.GreenLevel);
        
        half_cod =0.5*255;
        % Formula to create sine checkers
        for i =1:2:10
            rng('shuffle');
            an =2* pi* rand - pi;
            switch obj.stimParams.gratingColor
                    case colorBlackAndWhite
                        grating = zeros([size(R), 1]);
                        grating(:,:,1) = round(obj.stimParams.mean * ones(size(R)) + obj.stimParams.amplitude*sin(2*pi* cyclePerPixel * R) .* sin((2*pi*obj.stimParams.cyclesPerRotation/(2*pi)*T)-an));        
                    case colorRedAndGreen
                        grating = zeros([size(R), 3]);
                        sinMatrix = sin(2*pi* cyclePerPixel * R) .* sin((2*pi*obj.stimParams.cyclesPerRotation/(2*pi)*T)-an);
                        grating(:,:,1) = round(obj.stimParams.mean * ones(size(R)) + (Redlevel(1)-half_cod)*(sinMatrix.*(sinMatrix >= 0))-(half_cod-Greenlevel(1))*abs(sinMatrix.*(sinMatrix <= 0)));
                        grating(:,:,2) = round(obj.stimParams.mean * ones(size(R)) + (Greenlevel(2)-half_cod)*abs(sinMatrix.*(sinMatrix <= 0))-(half_cod-Redlevel(2))*(sinMatrix.*(sinMatrix >= 0)));
            end
            obj.tex(i) = Screen('MakeTexture', screenProperties.window, grating);
    
            % Flip contrast
            switch obj.stimParams.gratingColor
                case colorBlackAndWhite
                        grating(:,:,1) = round(obj.stimParams.mean * ones(size(R)) - obj.stimParams.amplitude*sin(2*pi* cyclePerPixel * R) .* sin((2*pi*obj.stimParams.cyclesPerRotation/(2*pi)*T)-an));
                case colorRedAndGreen
                        grating(:,:,2) = round(obj.stimParams.mean * ones(size(R)) + (Greenlevel(2)-half_cod)*(sinMatrix.*(sinMatrix >= 0))-(half_cod-Redlevel(2))*abs(sinMatrix.*(sinMatrix <= 0)));
                        grating(:,:,1) = round(obj.stimParams.mean * ones(size(R)) + (Redlevel(1)-half_cod)*abs(sinMatrix.*(sinMatrix <= 0))-(half_cod-Greenlevel(1))*(sinMatrix.*(sinMatrix >= 0))); 
            end
            obj.tex(i+1) = Screen('MakeTexture', screenProperties.window, grating);
        end
        obj.lastSwitchTime = 0;
        obj.lasttaghir = 0;
        obj.phaseDirection = 1;
        obj.show = 1;
      end

      % Timing setup of presentation
      function texture = getNextTexture(obj, timeProperties)
          
        if obj.lastSwitchTime == 0
            obj.lastSwitchTime = timeProperties.t;
        end

        if timeProperties.t > obj.lastSwitchTime + (1/obj.flickerFrequency)/2
			obj.show = obj.show * -1;
            % offset so current frame is same number while going backwards
			obj.lastSwitchTime = timeProperties.t;
        end
                
  %% moving checkers
        if obj.lasttaghir == 0
            obj.lasttaghir = timeProperties.t;
        end

        if timeProperties.t > obj.lasttaghir + 2 % time of change
            obj.phaseDirection = obj.phaseDirection +1;
			obj.lasttaghir = timeProperties.t;
        end
                
        if obj.phaseDirection == 1
            if obj.show ==1
                texture = obj.tex(1);
            else
                texture = obj.tex(2);
            end
        elseif obj.phaseDirection == 2
            if obj.show ==1
                texture = obj.tex(3);
            else
                texture = obj.tex(4);
            end
       elseif obj.phaseDirection == 3
            if obj.show ==1
                texture = obj.tex(5);
            else
                texture = obj.tex(6);
            end
      elseif obj.phaseDirection == 4
            if obj.show ==1
                texture = obj.tex(7);
            else
                texture = obj.tex(8);
            end
      elseif obj.phaseDirection == 5

            if obj.show ==1
                texture = obj.tex(9);
            else
                texture = obj.tex(10);
            end 
      else 
           if obj.show ==1
                texture = obj.tex(1);
           else
                texture = obj.tex(2);
            end 
     end


      end
      
   end
end
